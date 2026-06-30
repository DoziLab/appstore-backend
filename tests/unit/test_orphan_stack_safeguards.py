"""Tests for the orphan-stack-id safeguards.

Two related guarantees, tested independently:

1. ``_provision_one_stack_assignment`` invokes the ``on_stack_created``
   callback IMMEDIATELY after ``heat_service.create_stack`` returns —
   before the long-running Ansible phase. Without that callback, a
   worker crash mid-Ansible would leave the Heat stack alive in
   OpenStack with no entry in ``deployment.openstack_stack_id`` for
   ``delete_deployment`` to find.

2. ``_collect_stack_ids_for_cleanup`` walks BOTH ``deployment.openstack_stack_id``
   AND ``DeploymentInstance.openstack_server_id`` and returns the union
   (deduplicated, insertion order preserved). This is the defensive
   fallback for any orphan that slipped past safeguard #1 — a redeploy
   from a previous deploy build that didn't have it.

These behaviors are policy, not implementation detail — both have to
hold for the orphan-stack guarantee to be real.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.tasks import deploy_tasks


# ---------------------------------------------------------------------------
# on_stack_created — fires immediately after create_stack
# ---------------------------------------------------------------------------


def _make_template_context():
    """Minimal context the helper needs. ``split_parameters`` returns
    empty Heat + Ansible dicts so we don't have to thread real params."""
    ctx = MagicMock()
    ctx.split_parameters.return_value = ({}, {})
    ctx.heat_template = "heat: {}"
    ctx.files_dict = {}
    ctx.credentials_spec = {"per_group": [], "teacher": []}
    ctx.playbooks = []         # disables the Ansible branch
    ctx.scripts = {}
    ctx.template_files = {}
    return ctx


def _make_deployment_row():
    return SimpleNamespace(
        id="dep-1",
        name="dep",
        course_id="course-1",
        template_version_id="tv-1",
    )


def _make_stack_assignment_data():
    return {
        "stack_index": 1,
        "groups": [{
            "group_name": "G1", "group_index": 1,
            "students": [], "course_group_id": "grp-1",
        }],
    }


def _teacher_info():
    return {
        "id": "kc-teacher", "username": "prof",
        "email": "p@x.de", "first_name": "Prof", "last_name": "X",
    }


def test_on_stack_created_fires_before_credential_persistence():
    """The callback must run AS SOON AS Heat returns a stack id — before
    the credential-persistence call that creates the DeploymentInstance
    row, and before Ansible. We assert the order via a shared list."""
    events: list[str] = []

    heat = MagicMock()
    def _create_stack(**_kwargs):
        events.append("heat.create_stack")
        return {"stack_id": "stack-NEW", "floating_ip": "1.2.3.4", "outputs": {}}
    heat.create_stack.side_effect = _create_stack

    fake_instance = MagicMock(id="inst-NEW")
    persist_mock = MagicMock(return_value=fake_instance)
    def _persist(**_kwargs):
        events.append("credentials.persist")
        return fake_instance
    persist_mock.side_effect = _persist

    def _on_stack_created(sid: str) -> None:
        events.append(f"callback({sid})")

    db = MagicMock()

    with (
        patch.object(
            deploy_tasks.DeploymentCredentialService,
            "persist_credentials_for_stack",
            persist_mock,
        ),
        patch.object(
            deploy_tasks.CredentialGeneratorService,
            "generate",
            return_value={"deployment_groups": [], "teacher": {}},
        ),
        patch.object(deploy_tasks, "get_settings", return_value=SimpleNamespace(
            ansible_ssh_private_key="", ansible_ssh_key_name="kp",
        )),
    ):
        stack_id, instance = deploy_tasks._provision_one_stack_assignment(
            db=db,
            deployment=_make_deployment_row(),
            stack_assignment_data=_make_stack_assignment_data(),
            template_context=_make_template_context(),
            heat_service=heat,
            ansible_service_factory=lambda **kw: MagicMock(),
            log_service=MagicMock(),
            all_parameters={},
            teacher_info=_teacher_info(),
            stack_name="dep-s1-abcd",
            stack_index=1,
            total_stacks=1,
            on_stack_created=_on_stack_created,
        )

    assert stack_id == "stack-NEW"
    assert instance is fake_instance
    # The callback ran AFTER Heat but BEFORE credentials.persist (which
    # is itself before Ansible — Ansible is gated out by empty playbooks).
    # If a future refactor moves credential persistence above the callback
    # this assertion catches it: the callback must close the orphan
    # window first.
    assert events.index("callback(stack-NEW)") < events.index("credentials.persist")
    assert events.index("heat.create_stack") < events.index("callback(stack-NEW)")


def test_on_stack_created_failure_is_swallowed_not_fatal():
    """A failing callback must not abort the provisioning — Ansible /
    credential persistence are the actual contract, the callback is a
    best-effort safety net. The helper logs and continues."""
    heat = MagicMock()
    heat.create_stack.return_value = {"stack_id": "stack-NEW", "floating_ip": "1.2.3.4", "outputs": {}}

    fake_instance = MagicMock(id="inst-NEW")
    with (
        patch.object(
            deploy_tasks.DeploymentCredentialService,
            "persist_credentials_for_stack",
            return_value=fake_instance,
        ),
        patch.object(
            deploy_tasks.CredentialGeneratorService,
            "generate",
            return_value={"deployment_groups": [], "teacher": {}},
        ),
        patch.object(deploy_tasks, "get_settings", return_value=SimpleNamespace(
            ansible_ssh_private_key="", ansible_ssh_key_name="kp",
        )),
    ):
        stack_id, instance = deploy_tasks._provision_one_stack_assignment(
            db=MagicMock(),
            deployment=_make_deployment_row(),
            stack_assignment_data=_make_stack_assignment_data(),
            template_context=_make_template_context(),
            heat_service=heat,
            ansible_service_factory=lambda **kw: MagicMock(),
            log_service=MagicMock(),
            all_parameters={},
            teacher_info=_teacher_info(),
            stack_name="dep-s1-abcd",
            stack_index=1,
            total_stacks=1,
            on_stack_created=lambda _sid: (_ for _ in ()).throw(RuntimeError("db down")),
        )

    # Provisioning still succeeded.
    assert stack_id == "stack-NEW"
    assert instance is fake_instance


def test_on_stack_created_omitted_is_allowed():
    """The callback is optional — when None, the helper just doesn't
    invoke it. Used by code paths that don't need eager persistence
    (or by tests that don't care)."""
    heat = MagicMock()
    heat.create_stack.return_value = {"stack_id": "stack-X", "floating_ip": "", "outputs": {}}

    fake_instance = MagicMock(id="inst-X")
    with (
        patch.object(
            deploy_tasks.DeploymentCredentialService,
            "persist_credentials_for_stack",
            return_value=fake_instance,
        ),
        patch.object(
            deploy_tasks.CredentialGeneratorService,
            "generate",
            return_value={"deployment_groups": [], "teacher": {}},
        ),
        patch.object(deploy_tasks, "get_settings", return_value=SimpleNamespace(
            ansible_ssh_private_key="", ansible_ssh_key_name="kp",
        )),
    ):
        stack_id, _ = deploy_tasks._provision_one_stack_assignment(
            db=MagicMock(),
            deployment=_make_deployment_row(),
            stack_assignment_data=_make_stack_assignment_data(),
            template_context=_make_template_context(),
            heat_service=heat,
            ansible_service_factory=lambda **kw: MagicMock(),
            log_service=MagicMock(),
            all_parameters={},
            teacher_info=_teacher_info(),
            stack_name="dep-s1-abcd",
            stack_index=1,
            total_stacks=1,
            # on_stack_created omitted on purpose
        )
    assert stack_id == "stack-X"


# ---------------------------------------------------------------------------
# _collect_stack_ids_for_cleanup — union with DeploymentInstance fallback
# ---------------------------------------------------------------------------


def _make_db_with_instances(*instances):
    """Build a MagicMock db whose ``query(DeploymentInstance).filter(...).all()``
    returns the given instance stubs."""
    db = MagicMock()
    chain = MagicMock()
    chain.filter.return_value.all.return_value = list(instances)
    db.query.return_value = chain
    return db


def test_collect_stack_ids_unions_deployment_and_instance_sources():
    """Stack ids from the deployment row come first; instance rows
    contribute any additional ids that aren't already in the array.
    The exact dedup-while-preserving-order is what makes the fallback
    safe to combine with the primary source."""
    dep = SimpleNamespace(
        id="dep-1",
        openstack_stack_id=json.dumps(["A", "B"]),
    )
    instances = [
        SimpleNamespace(id="inst-1", openstack_server_id="B"),   # dup
        SimpleNamespace(id="inst-2", openstack_server_id="C"),   # new!
        SimpleNamespace(id="inst-3", openstack_server_id=None),  # ignored
    ]
    db = _make_db_with_instances(*instances)

    out = deploy_tasks._collect_stack_ids_for_cleanup(db, dep)
    assert out == ["A", "B", "C"]


def test_collect_stack_ids_handles_null_openstack_stack_id():
    """Deployment with no array but with one instance row whose
    openstack_server_id IS set — that single id must still survive
    (this is exactly the orphan scenario the fallback exists for)."""
    dep = SimpleNamespace(id="dep-1", openstack_stack_id=None)
    instances = [SimpleNamespace(id="inst-1", openstack_server_id="orphan-X")]
    db = _make_db_with_instances(*instances)

    assert deploy_tasks._collect_stack_ids_for_cleanup(db, dep) == ["orphan-X"]


def test_collect_stack_ids_handles_empty_json_array():
    """The dangerous-but-real shape: redeploy left an empty list after
    deleting the OLD stack but before persisting the NEW one. Instance
    row still has the new id."""
    dep = SimpleNamespace(id="dep-1", openstack_stack_id="[]")
    instances = [SimpleNamespace(id="inst-1", openstack_server_id="new-stack-id")]
    db = _make_db_with_instances(*instances)

    assert deploy_tasks._collect_stack_ids_for_cleanup(db, dep) == ["new-stack-id"]


def test_collect_stack_ids_handles_legacy_single_string():
    """Older rows persisted a bare stack id, not a JSON array. Treat as
    a single id, don't error out."""
    dep = SimpleNamespace(id="dep-1", openstack_stack_id="legacy-id")
    db = _make_db_with_instances()

    assert deploy_tasks._collect_stack_ids_for_cleanup(db, dep) == ["legacy-id"]


def test_collect_stack_ids_returns_empty_when_no_sources():
    dep = SimpleNamespace(id="dep-1", openstack_stack_id=None)
    db = _make_db_with_instances()
    assert deploy_tasks._collect_stack_ids_for_cleanup(db, dep) == []


def test_collect_stack_ids_swallows_instance_query_errors():
    """A broken instances relationship must not crash the cleanup — the
    primary source (deployment.openstack_stack_id) still gets returned."""
    dep = SimpleNamespace(id="dep-1", openstack_stack_id=json.dumps(["A"]))
    db = MagicMock()
    db.query.side_effect = RuntimeError("db down")

    assert deploy_tasks._collect_stack_ids_for_cleanup(db, dep) == ["A"]
