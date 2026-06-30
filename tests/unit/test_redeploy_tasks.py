"""Tests for the redeploy_instance / redeploy_deployment Celery tasks
and the parameter-override helpers in src.tasks.deploy_tasks.

The redeploy paths bundle four pieces of policy worth covering with
unit tests, none of which need a live OpenStack or DB:

1. ``_merge_parameter_layers`` — order is base → deployment → instance,
   with later layers winning. Empty / None layers are no-ops.

2. ``_reconstruct_stack_assignment_for_instance`` — recovers the
   ``StackAssignment`` payload that produced an instance from the
   ``-s<idx>-<dep4>`` suffix in ``vm_name``. Mis-named instances
   return None (caller treats as fatal).

3. ``redeploy_instance`` — the orchestration: instance flips to
   REDEPLOYING, old stack is deleted, ``_provision_one_stack_assignment``
   is called with the merged params, the deployment's stack-id JSON
   array is rewritten on the way through.

4. ``redeploy_deployment`` — iterates instances sequentially and folds
   per-instance overrides into the deployment-wide map before calling
   ``redeploy_instance``.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.models.deployment_instance import DeploymentInstanceStatus
from src.tasks import deploy_tasks


_DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000abc"
_INSTANCE_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# _merge_parameter_layers
# ---------------------------------------------------------------------------


def test_merge_layers_later_wins():
    """Deployment override beats base, instance override beats deployment."""
    base = {"a": 1, "b": 2, "c": 3}
    dep = {"b": 20, "d": 40}
    inst = {"c": 300}

    result = deploy_tasks._merge_parameter_layers(
        base=base, deployment_overrides=dep, instance_overrides=inst
    )

    assert result == {"a": 1, "b": 20, "c": 300, "d": 40}
    # Inputs are not mutated.
    assert base == {"a": 1, "b": 2, "c": 3}
    assert dep == {"b": 20, "d": 40}
    assert inst == {"c": 300}


def test_merge_layers_none_skipped():
    """None / empty layers are no-ops; base survives untouched."""
    base = {"x": 1}
    assert deploy_tasks._merge_parameter_layers(
        base=base, deployment_overrides=None, instance_overrides=None
    ) == {"x": 1}
    assert deploy_tasks._merge_parameter_layers(
        base=base, deployment_overrides={}, instance_overrides={}
    ) == {"x": 1}


def test_merge_layers_only_deployment():
    """Deployment-only override paths (used by the per-instance endpoint)."""
    base = {"x": 1}
    assert deploy_tasks._merge_parameter_layers(
        base=base, deployment_overrides={"y": 2}, instance_overrides=None
    ) == {"x": 1, "y": 2}


# ---------------------------------------------------------------------------
# _reconstruct_stack_assignment_for_instance
# ---------------------------------------------------------------------------


def test_reconstruct_picks_correct_assignment_by_suffix():
    """Heat names follow ``<name>-s<idx>-<dep4>`` — we recover ``<idx>``."""
    raw = [{"stack_index": 1, "tag": "A"}, {"stack_index": 2, "tag": "B"}, {"stack_index": 3, "tag": "C"}]
    inst = SimpleNamespace(vm_name="sql-kurs-s2-abcd")

    chosen = deploy_tasks._reconstruct_stack_assignment_for_instance(inst, raw)
    assert chosen == {"stack_index": 2, "tag": "B"}


def test_reconstruct_handles_dashes_in_deployment_name():
    """Deployment names may contain dashes — the ``-s<idx>-`` suffix is
    matched right-to-left so the dashes in the prefix don't confuse it."""
    raw = [{"stack_index": 1}, {"stack_index": 2}]
    inst = SimpleNamespace(vm_name="sql-kurs-summer-2026-s2-1234")

    chosen = deploy_tasks._reconstruct_stack_assignment_for_instance(inst, raw)
    assert chosen == {"stack_index": 2}


def test_reconstruct_returns_none_for_bad_name():
    """A wedged / legacy vm_name → None (caller fails the redeploy)."""
    raw = [{"stack_index": 1}]
    assert deploy_tasks._reconstruct_stack_assignment_for_instance(
        SimpleNamespace(vm_name=None), raw
    ) is None
    assert deploy_tasks._reconstruct_stack_assignment_for_instance(
        SimpleNamespace(vm_name="not-a-valid-name"), raw
    ) is None


def test_reconstruct_returns_none_when_index_out_of_range():
    """A name that parses but points past the assignments list is unsafe."""
    raw = [{"stack_index": 1}]
    inst = SimpleNamespace(vm_name="dep-s7-abcd")
    assert deploy_tasks._reconstruct_stack_assignment_for_instance(inst, raw) is None


def test_stack_index_for_instance_fallback():
    """Fallback to 1 when no index suffix is parseable — keeps the redeploy
    able to log even if the name was hand-edited."""
    assert deploy_tasks._stack_index_for_instance(
        SimpleNamespace(vm_name="dep-s3-abcd"), []
    ) == 3
    assert deploy_tasks._stack_index_for_instance(
        SimpleNamespace(vm_name="bogus"), []
    ) == 1


# ---------------------------------------------------------------------------
# _build_stack_name
# ---------------------------------------------------------------------------


def test_build_stack_name_matches_deploy_format():
    """Redeploy must produce the same Heat-safe slug as the initial deploy
    so a redeployed VM still matches its stack tag pattern."""
    dep = SimpleNamespace(id="abcd1234-xxxx", name="SQL Kurs Sommer_2026")
    assert deploy_tasks._build_stack_name(dep, 3) == "sql-kurs-sommer-2026-s3-abcd"


def test_build_stack_name_truncates_to_64_chars():
    dep = SimpleNamespace(id="abcd1234", name="X" * 100)
    name = deploy_tasks._build_stack_name(dep, 1)
    assert len(name) <= 64


# ---------------------------------------------------------------------------
# _snapshot_instance_credentials (preserve_credentials path)
#
# The snapshot's contract changed: instead of round-tripping access rows
# back into ``generated``-shaped per-group/teacher buckets (which was
# lossy — public_key, port, connection_url, and the original app.yaml
# credential type were all dropped), it now captures every field of each
# ``DeploymentInstanceAccess`` row verbatim under ``_preserved_access``,
# ready for ``_rebind_preserved_access_rows`` to re-attach to the new
# instance after persistence. ``deployment_groups`` and ``teacher`` come
# back empty by design — Ansible still receives fresh creds, the DB rows
# are rebound separately.
# ---------------------------------------------------------------------------


def test_snapshot_credentials_captures_all_access_row_fields_verbatim():
    """SSH + non-SSH rows survive the snapshot with port / connection_url
    / ssh_private_key intact, ready for rebinding."""
    ssh = SimpleNamespace(
        access_type=SimpleNamespace(value="ssh"),
        username="g1", password="pw1", ssh_private_key="key1",
        connection_url="ssh g1@1.2.3.4", port=22,
        group_id="grp-1", is_active=True, expires_at=None,
    )
    db_row = SimpleNamespace(
        access_type=SimpleNamespace(value="database"),
        username="dbu", password="dbpw", ssh_private_key=None,
        connection_url="https://pgadmin.example/", port=80,
        group_id="grp-1", is_active=True, expires_at=None,
    )
    admin = SimpleNamespace(
        access_type=SimpleNamespace(value="ssh"),
        username="teacher", password="adminpw", ssh_private_key="adminkey",
        connection_url="ssh teacher@1.2.3.4", port=22,
        group_id=None, is_active=True, expires_at=None,
    )
    instance = SimpleNamespace(access_methods=[ssh, db_row, admin])

    snap = deploy_tasks._snapshot_instance_credentials(MagicMock(), instance)

    # The shim fields stay empty on purpose — preserved data lives under
    # _preserved_access and is rebound from there.
    assert snap["deployment_groups"] == []
    assert snap["teacher"] == {}

    rows = snap["_preserved_access"]
    assert len(rows) == 3
    # Every column we care about for student logins is present verbatim.
    assert rows[0]["username"] == "g1"
    assert rows[0]["password"] == "pw1"
    assert rows[0]["ssh_private_key"] == "key1"
    assert rows[0]["port"] == 22
    assert rows[0]["connection_url"] == "ssh g1@1.2.3.4"
    assert rows[1]["connection_url"] == "https://pgadmin.example/"
    assert rows[1]["port"] == 80
    assert rows[2]["group_id"] is None  # teacher row


# ---------------------------------------------------------------------------
# redeploy_instance — orchestration
# ---------------------------------------------------------------------------


def _make_instance(*, vm_name="dep-s1-abcd", access_methods=None):
    """Build a stub ``DeploymentInstance`` row good enough for the redeploy
    task. Status is a real enum so the ``.value`` lookup works the same way
    the production code expects."""
    inst = MagicMock()
    inst.id = _INSTANCE_ID
    inst.vm_name = vm_name
    inst.openstack_server_id = "old-stack-id"
    inst.deployment_id = _DEPLOYMENT_ID
    inst.access_methods = access_methods or []
    inst.status = DeploymentInstanceStatus.RUNNING
    return inst


def _make_deployment(*, stack_ids=("old-stack-id",), parameters=None, stack_assignments=None):
    params_payload = {
        "parameters": parameters or {"include_notebooks": True},
        "stack_assignments": stack_assignments or [{"stack_index": 1, "groups": [{
            "group_name": "G1", "group_index": 1, "students": [], "course_group_id": "grp-1",
        }]}],
        "teacher": {
            "id": "kc-teacher", "username": "prof", "email": "p@x.de",
            "first_name": "Prof", "last_name": "X",
        },
    }
    return SimpleNamespace(
        id=_DEPLOYMENT_ID,
        name="dep",
        course_id="course-1",
        template_version_id="tv-1",
        openstack_stack_id=json.dumps(list(stack_ids)),
        deployment_parameters=json.dumps(params_payload),
        openstack_project=SimpleNamespace(id="proj-1"),
    )


def _patch_redeploy_environment(*, deployment, instance, provision_return=None):
    """Patch every collaborator of redeploy_instance with MagicMocks and
    return them so the test can assert on call args.

    Returns a dict with all the patches' return values for convenience.
    """
    session = MagicMock()

    # db.query(DeploymentInstance).filter(...).first() → instance
    inst_filter = MagicMock()
    inst_filter.first.return_value = instance
    inst_query = MagicMock()
    inst_query.filter.return_value = inst_filter

    # db.query(DeploymentInstanceAccess).filter(...).delete()
    access_filter = MagicMock()
    access_filter.delete.return_value = 0
    access_query = MagicMock()
    access_query.filter.return_value = access_filter

    # Map .query(Model) to the right stub.
    def _query(model):
        from src.models.deployment_instance import DeploymentInstance as DI
        from src.models.deployment_instance_access import DeploymentInstanceAccess as DIA
        if model is DI:
            return inst_query
        if model is DIA:
            return access_query
        return MagicMock()
    session.query.side_effect = _query

    repo = MagicMock()
    repo.get_by_id.return_value = deployment

    log_service = MagicMock()
    file_service = MagicMock()

    heat = MagicMock()
    heat.delete_stack.return_value = True

    template_context = MagicMock()
    template_context.split_parameters.return_value = ({}, {})

    return {
        "session": session,
        "repo": repo,
        "log_service": log_service,
        "file_service": file_service,
        "heat": heat,
        "template_context": template_context,
        "provision_return": provision_return,
    }


def _run_redeploy_instance(env, *, deployment_overrides=None, preserve_credentials=False):
    """Run the redeploy_instance task with a fully patched environment.

    Returns the task result dict.
    """
    new_instance = MagicMock(id="new-instance-id")
    provision_return = env.get("provision_return") or ("new-stack-id", new_instance)

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=env["session"]),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=env["repo"]),
        patch.object(deploy_tasks, "DeploymentLogService", return_value=env["log_service"]),
        patch.object(deploy_tasks, "TemplateVersionFileService", return_value=env["file_service"]),
        patch.object(deploy_tasks, "HeatStackService", return_value=env["heat"]),
        patch.object(deploy_tasks, "_load_template_context", return_value=env["template_context"]),
        patch.object(deploy_tasks, "_provision_one_stack_assignment", return_value=provision_return) as provision_mock,
        patch.object(deploy_tasks, "get_settings", return_value=SimpleNamespace(
            ansible_ssh_private_key="", ansible_ssh_key_name="kp",
        )),
    ):
        result = deploy_tasks.redeploy_instance.run(
            _DEPLOYMENT_ID,
            _INSTANCE_ID,
            deployment_parameter_overrides=deployment_overrides,
            preserve_credentials=preserve_credentials,
        )
    return result, provision_mock


def test_redeploy_instance_happy_path_flips_status_and_calls_provision():
    """REDEPLOYING is set before the old stack is torn down, and the
    provision helper is invoked with the recovered stack assignment."""
    deployment = _make_deployment(stack_ids=("old-stack-id", "sibling"))
    instance = _make_instance(vm_name="dep-s1-abcd")

    env = _patch_redeploy_environment(deployment=deployment, instance=instance)
    result, provision_mock = _run_redeploy_instance(env)

    assert result["status"] == "redeployed"
    assert result["new_stack_id"] == "new-stack-id"
    assert result["new_instance_id"] == "new-instance-id"
    # Status was flipped to REDEPLOYING during the task.
    assert instance.status == DeploymentInstanceStatus.REDEPLOYING
    # Old Heat stack was deleted.
    env["heat"].delete_stack.assert_called_once_with("old-stack-id")
    # Provision helper got called with the merged params.
    provision_mock.assert_called_once()
    kwargs = provision_mock.call_args.kwargs
    assert kwargs["stack_index"] == 1
    # No overrides → effective params equal the deployment's stored ones.
    assert kwargs["all_parameters"] == {"include_notebooks": True}
    # Single-instance redeploy → no preserved user_json.
    assert kwargs["preserved_user_json"] is None


def test_redeploy_instance_overrides_are_merged_into_effective_params():
    """A deployment-level override wins over the stored parameter."""
    deployment = _make_deployment(parameters={"flag": False, "size": "small"})
    instance = _make_instance(vm_name="dep-s1-abcd")

    env = _patch_redeploy_environment(deployment=deployment, instance=instance)
    result, provision_mock = _run_redeploy_instance(
        env, deployment_overrides={"flag": True, "extra": 42}
    )

    assert result["status"] == "redeployed"
    kwargs = provision_mock.call_args.kwargs
    assert kwargs["all_parameters"] == {"flag": True, "size": "small", "extra": 42}


def test_redeploy_instance_preserve_credentials_carries_snapshot_in():
    """When preserve_credentials=True the provision helper is handed the
    snapshot dict containing every access-row field. The rebind step
    (called from inside _provision_one_stack_assignment, which is mocked
    here) is what actually re-attaches them — we only verify the snapshot
    travels far enough to reach it."""
    ssh = SimpleNamespace(
        access_type=SimpleNamespace(value="ssh"),
        username="g1", password="pw1", ssh_private_key="k1",
        connection_url="ssh g1@1.2.3.4", port=22,
        group_id="grp-1", is_active=True, expires_at=None,
    )
    instance = _make_instance(vm_name="dep-s1-abcd", access_methods=[ssh])
    deployment = _make_deployment()

    env = _patch_redeploy_environment(deployment=deployment, instance=instance)
    _, provision_mock = _run_redeploy_instance(env, preserve_credentials=True)

    preserved = provision_mock.call_args.kwargs["preserved_user_json"]
    assert preserved is not None
    rows = preserved["_preserved_access"]
    assert len(rows) == 1
    assert rows[0]["username"] == "g1"
    assert rows[0]["ssh_private_key"] == "k1"
    assert rows[0]["port"] == 22
    assert rows[0]["group_id"] == "grp-1"


def test_redeploy_instance_rewrites_stack_id_list_on_deployment():
    """The deployment's openstack_stack_id JSON loses the old id and
    gains the new one — so a future delete walks the right list."""
    deployment = _make_deployment(stack_ids=("old-stack-id", "sibling-stack"))
    instance = _make_instance(vm_name="dep-s1-abcd")

    env = _patch_redeploy_environment(deployment=deployment, instance=instance)
    result, _ = _run_redeploy_instance(env)

    assert result["status"] == "redeployed"
    final_ids = json.loads(deployment.openstack_stack_id)
    assert "old-stack-id" not in final_ids
    assert "sibling-stack" in final_ids
    assert "new-stack-id" in final_ids


def test_redeploy_instance_fails_when_stack_assignment_missing():
    """An instance whose name can't be reconstructed → fatal redeploy.
    Status flips to FAILED, no provision helper call, no Heat delete."""
    deployment = _make_deployment(stack_assignments=[])
    instance = _make_instance(vm_name="legacy-no-suffix")

    env = _patch_redeploy_environment(deployment=deployment, instance=instance)
    result, provision_mock = _run_redeploy_instance(env)

    assert result["status"] == "failed"
    assert "stack_assignment" in result["error"]
    provision_mock.assert_not_called()
    env["heat"].delete_stack.assert_not_called()
    assert instance.status == DeploymentInstanceStatus.FAILED


def test_redeploy_instance_heat_delete_failure_marks_failed():
    """Heat refusing to delete the old stack must NOT remove the row;
    instance flips to FAILED so the user can retry."""
    deployment = _make_deployment()
    instance = _make_instance(vm_name="dep-s1-abcd")

    env = _patch_redeploy_environment(deployment=deployment, instance=instance)
    env["heat"].delete_stack.side_effect = RuntimeError("openstack 500")

    result, provision_mock = _run_redeploy_instance(env)

    assert result["status"] == "failed"
    provision_mock.assert_not_called()


# ---------------------------------------------------------------------------
# redeploy_deployment — fan-out over instances
# ---------------------------------------------------------------------------


def test_redeploy_deployment_iterates_instances_with_merged_per_vm_overrides():
    """Per-instance overrides are folded into the deployment-wide map on
    the way through, so each redeploy_instance call sees its own merged
    override dict."""
    deployment = _make_deployment()
    inst_a = SimpleNamespace(id="inst-A", created_at=1)
    inst_b = SimpleNamespace(id="inst-B", created_at=2)

    session = MagicMock()
    # db.query(DeploymentInstance).filter(...).order_by(...).all() → [inst_a, inst_b]
    instances_chain = MagicMock()
    instances_chain.filter.return_value.order_by.return_value.all.return_value = [inst_a, inst_b]
    session.query.return_value = instances_chain

    repo = MagicMock()
    repo.get_by_id.return_value = deployment

    redeploy_calls: list[dict] = []

    def _fake_redeploy_instance_run(**kwargs):
        redeploy_calls.append(kwargs)
        return {"status": "redeployed", "instance_id": kwargs.get("instance_id")}

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=session),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=repo),
        patch.object(deploy_tasks.redeploy_instance, "run", side_effect=_fake_redeploy_instance_run),
    ):
        result = deploy_tasks.redeploy_deployment.run(
            _DEPLOYMENT_ID,
            deployment_parameter_overrides={"flag": True},
            instance_parameter_overrides={"inst-B": {"flag": False, "extra": 1}},
            preserve_credentials=True,
        )

    assert result["status"] == "redeployed"
    assert len(redeploy_calls) == 2
    # inst_a inherits only the deployment-wide override.
    assert redeploy_calls[0]["instance_id"] == "inst-A"
    assert redeploy_calls[0]["deployment_parameter_overrides"] == {"flag": True}
    assert redeploy_calls[0]["preserve_credentials"] is True
    # inst_b gets the merged override map (instance wins over deployment).
    assert redeploy_calls[1]["instance_id"] == "inst-B"
    assert redeploy_calls[1]["deployment_parameter_overrides"] == {"flag": False, "extra": 1}


def test_redeploy_deployment_reports_partial_failure_when_one_instance_fails():
    """One failed instance → overall status flips to partial_failure but
    the loop still hits every instance."""
    deployment = _make_deployment()
    inst_a = SimpleNamespace(id="inst-A", created_at=1)
    inst_b = SimpleNamespace(id="inst-B", created_at=2)

    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [inst_a, inst_b]

    repo = MagicMock()
    repo.get_by_id.return_value = deployment

    def _fake(*, deployment_id, instance_id, **kwargs):
        if instance_id == "inst-A":
            return {"status": "failed", "instance_id": "inst-A"}
        return {"status": "redeployed", "instance_id": "inst-B"}

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=session),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=repo),
        patch.object(deploy_tasks.redeploy_instance, "run", side_effect=_fake),
    ):
        result = deploy_tasks.redeploy_deployment.run(_DEPLOYMENT_ID)

    assert result["status"] == "partial_failure"
    assert len(result["instance_results"]) == 2


def test_redeploy_deployment_returns_failed_when_no_instances():
    """A deployment with zero instance rows can't be redeployed."""
    deployment = _make_deployment()
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    repo = MagicMock()
    repo.get_by_id.return_value = deployment

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=session),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=repo),
    ):
        result = deploy_tasks.redeploy_deployment.run(_DEPLOYMENT_ID)

    assert result["status"] == "failed"
    assert "no instances" in result["error"].lower()
