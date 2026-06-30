"""Deploy tasks for Celery.

This module owns three lifecycle tasks that the API enqueues:

  * :func:`deploy_stack` — initial provisioning. For each ``stack_assignment``
    in ``deployment_parameters`` it creates a Heat stack, waits for SSH,
    copies scripts/files, runs the Ansible playbooks and persists credentials
    + access rows.
  * :func:`delete_deployment` — tears down every Heat stack the deployment
    owns and removes the DB row (only when ALL stacks were torn down OK; on
    partial failure the row stays so the user can retry).
  * :func:`restart_deployment` — triggers a Heat ``update_stack`` to
    refresh-in-place. Does NOT recreate or re-run Ansible.
  * :func:`redeploy_instance` — destroy-and-recreate a *single* VM
    (``DeploymentInstance``) inside an existing deployment, optionally with
    overridden parameters. The parent deployment stays RUNNING so the
    redeploy doesn't drag siblings down.
  * :func:`redeploy_deployment` — same as redeploy_instance, but iterates
    over every instance in the deployment. Used when the lecturer wants to
    apply a config change across the whole class without re-running the
    wizard.

The single-stack provisioning loop body lives in
:func:`_provision_one_stack_assignment` so both ``deploy_stack`` and
``redeploy_instance`` go through the same code path. That keeps
"credentials → heat → ansible → persist" identical for first-time deploys
and redeploys — drift here would be very expensive to debug.
"""
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import UUID

import yaml as _yaml

from src.celery_app import celery_app
from src.core.database import SessionLocal
from src.models.deployment import DeploymentStatus
from src.models.deployment_instance import DeploymentInstance, DeploymentInstanceStatus
from src.models.deployment_instance_access import DeploymentInstanceAccess
from src.models.deployment_log import DeploymentLogLevel, DeploymentLogEventType
from src.models.template_version_file import FileType
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.deployment_log_repository import DeploymentLogRepository
from src.services.template_version_file_service import TemplateVersionFileService
from src.services.deployment_log_service import DeploymentLogService
from src.services.deployment_credential_service import DeploymentCredentialService
from src.services.openstack_heat_service import HeatStackService
from src.services.ansible_service import AnsibleService
from src.services.credential_generator_service import CredentialGeneratorService
from src.utils.app_manifest_parser import AppManifestParser
from src.utils.cancellation import CancelledException, is_cancel_requested
from src.core.config import get_settings

logger = logging.getLogger(__name__)


# Heat parameters the backend ALWAYS owns — must never come from the
# wizard / override dicts. Kept as a module constant so both the initial
# deploy path and the redeploy path strip them out identically.
_BACKEND_MANAGED_HEAT_PARAMS = frozenset({"user_json", "key_name"})

# Bookkeeping keys present in ``generated`` but not actual credential
# types — must not leak into the ``applications`` section of user_json.
_NON_APP_KEYS = frozenset({
    "username", "email", "group_name", "group_index",
    "course_group_id", "students", "linux",
})


# ---------------------------------------------------------------------------
# Shared template / parameter loading helpers
# ---------------------------------------------------------------------------


class _TemplateContext:
    """Bundle of everything loaded once per deploy/redeploy task.

    Holds the template files, the parsed credentials spec, the playbooks
    sorted in the right order, and the parameter split (Heat vs Ansible)
    derived from the heat template's declared parameters.

    Centralising this keeps :func:`deploy_stack` and the redeploy paths in
    sync — when a new file type or parameter rule is added it lives here
    and both callers pick it up.
    """

    def __init__(
        self,
        *,
        heat_template: str,
        files_dict: dict[str, str],
        playbooks: list[tuple[str, str]],
        scripts: dict[str, str],
        template_files: dict[str, str],
        credentials_spec: dict[str, list],
        heat_defined_params: set[str],
    ) -> None:
        self.heat_template = heat_template
        self.files_dict = files_dict
        self.playbooks = playbooks
        self.scripts = scripts
        self.template_files = template_files
        self.credentials_spec = credentials_spec
        self.heat_defined_params = heat_defined_params

    def split_parameters(
        self, all_parameters: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Split a merged parameter dict into (heat, ansible) by what the
        heat template declares. Backend-managed Heat params are stripped so
        a malicious override can't bypass ``key_name`` / ``user_json``.
        """
        heat_params = {
            k: v for k, v in all_parameters.items()
            if k in self.heat_defined_params and k not in _BACKEND_MANAGED_HEAT_PARAMS
        }
        ansible_params = {
            k: v for k, v in all_parameters.items()
            if k not in self.heat_defined_params
        }
        return heat_params, ansible_params


def _load_template_context(
    file_service: TemplateVersionFileService,
    template_version_id: str,
) -> _TemplateContext | str:
    """Build a :class:`_TemplateContext` for the given template version.

    Returns the context on success, or a string error message on failure
    (caller is expected to forward that into ``_fail``). Implemented as a
    return-or-error pattern instead of raising so the call sites can stay
    aligned with the original loop's ``_fail`` shape.
    """
    files = file_service.get_version_files(
        template_version_id, include_content=True, skip_access_check=True
    )
    if not files:
        return f"No files found for template version {template_version_id}"

    heat_file = next((f for f in files if f.is_primary), None)
    if not heat_file or not heat_file.content:
        return "No primary Heat template found"

    try:
        heat_template_parsed = _yaml.safe_load(heat_file.content)
        heat_defined_params = set(heat_template_parsed.get("parameters", {}).keys())
    except Exception:
        heat_defined_params = set()

    # Parse app.yaml for credentials spec.
    app_yaml_file = next((f for f in files if f.file_name == "app.yaml"), None)
    credentials_spec: dict[str, list] = {"per_group": [], "teacher": []}
    if app_yaml_file and app_yaml_file.content:
        manifest = AppManifestParser.parse(app_yaml_file.content)
        credentials_spec = manifest.get("credentials", credentials_spec)

    # _common playbooks first (sorted), then template-specific.
    playbooks: list[tuple[str, str]] = []
    common_playbooks_dir = Path(__file__).parent.parent / "_common" / "playbooks"
    if common_playbooks_dir.exists():
        for common_file in sorted(common_playbooks_dir.glob("*.yml")):
            playbooks.append((f"_common/{common_file.name}", common_file.read_text()))

    scripts: dict[str, str] = {}
    template_files: dict[str, str] = {}
    for f in sorted(files, key=lambda x: (x.order, x.file_name)):
        if f.file_type == FileType.ANSIBLE_PLAYBOOK and f.content:
            playbooks.append((f.file_name, f.content))
        elif f.file_type == FileType.SHELL_SCRIPT and f.content:
            scripts[f.file_name] = f.content
        elif f.file_type == FileType.CONFIG_FILE and f.content:
            template_files[f.file_name] = f.content

    files_dict: dict[str, str] = {}
    for f in files:
        if f.file_type == FileType.CLOUD_INIT and f.content:
            files_dict["../cloud-init/user-data.yaml"] = f.content

    return _TemplateContext(
        heat_template=heat_file.content,
        files_dict=files_dict,
        playbooks=playbooks,
        scripts=scripts,
        template_files=template_files,
        credentials_spec=credentials_spec,
        heat_defined_params=heat_defined_params,
    )


# ---------------------------------------------------------------------------
# The single-stack provisioning unit, shared by deploy + redeploy
# ---------------------------------------------------------------------------


def _provision_one_stack_assignment(
    *,
    db,
    deployment,
    stack_assignment_data: dict,
    template_context: _TemplateContext,
    heat_service: HeatStackService,
    ansible_service_factory: Callable[..., AnsibleService],
    log_service: DeploymentLogService,
    all_parameters: dict[str, Any],
    teacher_info: dict,
    stack_name: str,
    stack_index: int,
    total_stacks: int,
    cancel_check: Callable[[], bool] | None = None,
    preserved_user_json: dict | None = None,
) -> tuple[Optional[str], Optional[DeploymentInstance]]:
    """Run the create-stack → Ansible → persist-credentials cycle for one
    stack assignment.

    Extracted verbatim from the original ``deploy_stack`` loop body. Both
    the initial deploy and the per-instance redeploy go through this so
    drift between the two paths stays impossible.

    Args:
        db: SQLAlchemy session.
        deployment: Deployment row (kept loaded throughout for tags / name).
        stack_assignment_data: One element of
            ``deployment_parameters['stack_assignments']``.
        template_context: Output of :func:`_load_template_context`.
        heat_service: A connected ``HeatStackService`` for the deployment's
            OpenStack project.
        ansible_service_factory: Callable that, given ``floating_ip`` and
            ``cancel_check``, returns an :class:`AnsibleService` bound to
            this db/deployment. Injected so tests can stub it out.
        log_service: Active ``DeploymentLogService`` instance.
        all_parameters: Effective (already-merged) parameter dict for THIS
            stack. Callers compute the merge — this function only splits
            it into Heat vs Ansible before use.
        teacher_info: ``deployment_parameters['teacher']`` payload, used
            to construct the credential admin block.
        stack_name: Final Heat stack name (already collision-safe).
        stack_index: 1-based position used only for log messages.
        total_stacks: Total count, also log-only.
        cancel_check: Optional predicate; when it returns True after Heat
            success the function logs the cancel and returns ``(stack_id,
            None)`` so the caller can short-circuit the rest of the loop.
            ``None`` (the default) disables cancellation entirely — used
            by the redeploy task, which is itself a discrete unit.
        preserved_user_json: When set, skip credential GENERATION and reuse
            this user_json verbatim. Used by ``redeploy_instance`` with
            ``preserve_credentials=True`` so students keep their logins.

    Returns:
        Tuple ``(stack_id, instance)``:
          * ``stack_id`` is the newly-created Heat stack ID, or ``None`` if
            creation failed before Heat reported back a usable ID.
          * ``instance`` is the persisted ``DeploymentInstance`` row, or
            ``None`` when persistence failed (the caller still gets the
            stack id for incremental persistence / cleanup).

    On Heat / Ansible failure the function re-raises after logging, so the
    caller's outer ``try/except`` can record the error and decide whether
    to continue with the next assignment (deploy_stack) or fail the redeploy.
    """
    from src.schemas.deployment import StackAssignment, TeacherInfo

    deployment_id = deployment.id
    stack_assignment = StackAssignment(**stack_assignment_data)
    teacher = TeacherInfo(**teacher_info)

    heat_parameters, ansible_parameters = template_context.split_parameters(all_parameters)

    # --- Generate credentials ---
    # ``preserved_user_json``, when set, is NOT a substitute for the
    # ``generated`` dict consumed by Heat / Ansible — it only carries access
    # rows we'll rebind onto the new instance after persistence (see
    # ``_rebind_preserved_access_rows``). Ansible still receives fresh creds
    # so the playbook is free to template them into config; we then overwrite
    # the DB-side access rows with the preserved set so students' logins keep
    # working in the credentials API. Playbooks that aren't idempotent on
    # passwords may still produce drift between what's on the VM and what's
    # in the DB — preserve_credentials is a best-effort guarantee.
    generated = CredentialGeneratorService.generate(
        credentials_spec=template_context.credentials_spec,
        stack_assignment=stack_assignment,
        teacher=teacher,
    )

    stack_params = {**heat_parameters}
    stack_params["key_name"] = get_settings().ansible_ssh_key_name
    tags = {
        "deployment_id": deployment_id,
        "course_id": deployment.course_id,
        "template_version_id": deployment.template_version_id,
        "stack_index": str(stack_index),
    }

    log_service.log(
        deployment_id=deployment_id,
        event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
        message=f"Creating Heat stack {stack_index}/{total_stacks}: {stack_name}",
        level=DeploymentLogLevel.INFO,
        details={"stack_index": stack_index, "stack_name": stack_name},
    )

    # --- 1. Create Heat stack ---
    stack_result = heat_service.create_stack(
        stack_name=stack_name,
        template=template_context.heat_template,
        parameters=stack_params,
        files=template_context.files_dict or None,
        tags=tags,
        timeout_mins=60,
    )
    stack_id: str = stack_result["stack_id"]

    log_service.log(
        deployment_id=deployment_id,
        event_type=DeploymentLogEventType.STACK_CREATE,
        message=f"Heat stack {stack_index} created: {stack_name}",
        level=DeploymentLogLevel.INFO,
        details={"stack_id": stack_id, "stack_name": stack_name, "stack_index": stack_index},
    )

    # --- 2. Build user_json + persist credentials ---
    # Credential persistence is load-bearing: without a DeploymentInstance row
    # the deployment has no DB record of the new VM, and the caller has no way
    # to retry or reach it. Bubble the exception up so the caller can record
    # the Heat-stack id as an orphan and report the failure to the user — the
    # previous "log and continue to Ansible" path silently produced an orphan
    # stack and a "redeployed" success response.
    credentials_for_db = _build_user_json(generated)
    try:
        instance = DeploymentCredentialService(db).persist_credentials_for_stack(
            deployment_id=deployment_id,
            stack_name=stack_name,
            openstack_stack_id=stack_id,
            user_json=credentials_for_db,
            floating_ip=stack_result.get("floating_ip") or "",
            heat_outputs=stack_result.get("outputs") or {},
            flavor=stack_params.get("flavor"),
        )
    except Exception as cred_error:
        logger.error(
            f"Failed to persist credentials for stack {stack_index}: {cred_error}",
            exc_info=True,
        )
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.FAILED,
            message=f"Stack {stack_index} created but credential persistence failed",
            level=DeploymentLogLevel.ERROR,
            details={"stack_index": stack_index, "error": str(cred_error)},
        )
        # Stamp the heat stack id onto the exception so the outer task can
        # record it as an orphan for later cleanup (same convention Heat's
        # create_stack uses on CREATE_FAILED / timeout).
        cred_error.stack_id = stack_id  # type: ignore[attr-defined]
        raise

    # If preserve_credentials is in play, replace the just-generated access
    # rows with the snapshot from the OLD instance so logins keep working.
    if preserved_user_json is not None:
        try:
            rebound = _rebind_preserved_access_rows(db, instance, preserved_user_json)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message=(
                    f"preserve_credentials: rebound {rebound} access row(s) "
                    f"from snapshot for stack {stack_index}"
                ),
                level=DeploymentLogLevel.INFO,
                details={"stack_index": stack_index, "rebound": rebound},
            )
        except Exception as rebind_err:
            # Rebinding is best-effort: failing here would leave fresh
            # auto-generated creds in place, which is recoverable. Log and
            # carry on rather than dropping the whole redeploy.
            logger.error(
                f"Failed to rebind preserved credentials for stack {stack_index}: {rebind_err}",
                exc_info=True,
            )
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=(
                    f"preserve_credentials: rebind failed for stack {stack_index}; "
                    "fresh credentials remain in place"
                ),
                level=DeploymentLogLevel.WARNING,
                details={"stack_index": stack_index, "error": str(rebind_err)},
            )

    # --- 3. Ansible (only if playbooks exist and SSH key available) ---
    ssh_private_key = get_settings().ansible_ssh_private_key or ""
    playbooks = template_context.playbooks
    if playbooks and ssh_private_key:
        floating_ip = stack_result.get("floating_ip", "")
        if not floating_ip:
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.ANSIBLE_FAILED,
                message=f"No floating_ip in stack result for stack {stack_index} — skipping Ansible",
                level=DeploymentLogLevel.WARNING,
            )
        else:
            if cancel_check and cancel_check():
                # Caller's deploy_stack uses the per-iteration checkpoint to
                # bail out cleanly; reuse the same shape here so the loop
                # outside can decide what to do.
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_DELETION_REQUESTED,
                    message=f"Cancel detected after Heat for stack {stack_index}; skipping Ansible",
                    level=DeploymentLogLevel.INFO,
                )
                return stack_id, instance

            ansible = ansible_service_factory(
                floating_ip=floating_ip,
                cancel_check=cancel_check,
            )
            try:
                ansible.wait_for_ssh()
                ansible.copy_files(
                    scripts=template_context.scripts,
                    files=template_context.template_files,
                )

                extra_vars = {
                    **generated,
                    **ansible_parameters,
                    "course_label": deployment.name,
                    "stack_label": stack_name,
                    "ssh_allow_users": [
                        s["linux"]["username"]
                        for s in generated.get("deployment_groups", [])
                        if s.get("linux", {}).get("password")
                    ],
                }
                ansible.run_playbooks(playbooks=playbooks, extra_vars=extra_vars)

                _maybe_persist_activation_links(
                    db=db,
                    log_service=log_service,
                    deployment_id=deployment_id,
                    stack_index=stack_index,
                    ansible=ansible,
                    instance=instance,
                    generated=generated,
                )
            except CancelledException:
                # Let the caller's outer handler decide whether this is a
                # cancel-success (deploy_stack) or a hard fail (redeploy).
                raise
    elif playbooks and not ssh_private_key:
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.ANSIBLE_FAILED,
            message="Playbooks defined but no SSH private key configured — skipping Ansible",
            level=DeploymentLogLevel.WARNING,
        )

    return stack_id, instance


def _build_user_json(generated: dict) -> dict:
    """Translate ``CredentialGeneratorService.generate`` output into the
    two-section ``user_json`` consumed by ``persist_credentials_for_stack``.

    Two-section layout:
      - ``instance.credentials`` / ``instance.admin_credentials``: SSH
        (Linux) credentials. Only emitted for templates whose app.yaml
        declares ``per_group.linux``; teacher always has an auto-generated
        linux block (admin key), so the admin SSH row is written for every
        template.
      - ``applications[]``: every NON-linux credential type declared in
        app.yaml (postgres, pgadmin, web_url, …). One ``applications``
        entry per credential type, with a ``credentials`` list for the
        groups and an ``admin_credentials`` block for the teacher.

    Extracted verbatim from the inlined logic in ``deploy_stack`` so the
    initial-deploy and redeploy paths produce identical user_json shapes.
    """
    group_entries = generated.get("deployment_groups", []) or []
    teacher_entry = generated.get("teacher", {}) or {}

    ssh_credentials = [
        {
            "username": s["linux"]["username"],
            "password": s["linux"]["password"],
            "ssh_private_key": (s.get("linux", {}).get("ssh_key") or {}).get("private_key"),
            "group_id": s.get("course_group_id"),
        }
        for s in group_entries
        if s.get("linux", {}).get("password")
    ]
    ssh_admin = (
        {
            "username": teacher_entry["linux"]["username"],
            "password": teacher_entry["linux"]["password"],
            "ssh_private_key": (teacher_entry["linux"].get("ssh_key") or {}).get("private_key"),
        }
        if teacher_entry.get("linux", {}).get("password")
        else None
    )

    # App-credentials section — collected per credential type by union of
    # keys across all group entries and the teacher entry (minus the
    # bookkeeping keys and ``linux``, which has its own SSH section).
    app_cred_types: list[str] = []
    for source in (*group_entries, teacher_entry):
        for key in source.keys():
            if key in _NON_APP_KEYS or key in app_cred_types:
                continue
            app_cred_types.append(key)

    applications = []
    for cred_type in app_cred_types:
        group_creds = []
        for s in group_entries:
            cred = s.get(cred_type)
            if not isinstance(cred, dict) or not cred.get("password"):
                continue
            group_creds.append({
                **cred,
                "group_id": s.get("course_group_id"),
            })
        admin_cred = teacher_entry.get(cred_type)
        admin_block = (
            admin_cred
            if isinstance(admin_cred, dict) and admin_cred.get("password")
            else None
        )
        if not group_creds and not admin_block:
            continue
        applications.append({
            "name": cred_type,
            "credentials": group_creds,
            "admin_credentials": admin_block,
        })

    return {
        "instance": {
            "credentials": ssh_credentials,
            "admin_credentials": ssh_admin,
        },
        "applications": applications,
    }


def _maybe_persist_activation_links(
    *,
    db,
    log_service: DeploymentLogService,
    deployment_id: str,
    stack_index: int,
    ansible: AnsibleService,
    instance: Optional[DeploymentInstance],
    generated: dict,
) -> None:
    """Post-Ansible fetch of /opt/dozilab/OVERLEAF_USERS.json and persistence
    of activation-link rows. No-op when the file is absent or instance
    persistence failed earlier.

    Same hardcoded path as before; the call is wrapped in a broad
    try/except so a single failed fetch never escalates to a deployment
    failure (the file still lives on the VM for manual recovery).
    """
    try:
        users_json = ansible.fetch_remote_json("/opt/dozilab/OVERLEAF_USERS.json")
        if users_json and instance is not None:
            username_to_group_id: dict[str, str | None] = {}
            for s in generated.get("deployment_groups", []):
                course_group_id = s.get("course_group_id")
                linux_username = s.get("linux", {}).get("username")
                if linux_username:
                    username_to_group_id[linux_username] = course_group_id
                top_username = s.get("username")
                if top_username:
                    username_to_group_id.setdefault(top_username, course_group_id)

            written = DeploymentCredentialService(db).persist_activation_links(
                instance_id=instance.id,
                overleaf_users_json=users_json,
                username_to_group_id=username_to_group_id,
            )
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.ANSIBLE_COMPLETED,
                message=f"Persisted {written} activation-link credential(s) for stack {stack_index}",
                level=DeploymentLogLevel.INFO,
                details={"stack_index": stack_index, "count": written},
            )
    except Exception as fetch_err:
        logger.warning(
            "Post-Ansible activation-link fetch failed for "
            f"deployment {deployment_id} stack {stack_index}: {fetch_err}",
            exc_info=True,
        )
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.ANSIBLE_COMPLETED,
            message=f"Stack {stack_index} done; activation-link fetch skipped: {fetch_err}",
            level=DeploymentLogLevel.WARNING,
            details={"stack_index": stack_index, "error": str(fetch_err)},
        )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(bind=True)
def deploy_stack(self, deployment_id: str) -> dict:
    """Deploy Heat stacks and run Ansible playbooks for a deployment.

    Flow per stack_assignment:
      1. Create Heat stack
      2. Wait for SSH
      3. Copy scripts/ and files/ to VM
      4. Run playbooks/ in order with generated credentials as extra-vars
    """
    task_id = self.request.id
    logger.info(f"Starting deployment task for deployment_id={deployment_id}, task_id={task_id}")

    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        log_service = DeploymentLogService(db)
        file_service = TemplateVersionFileService(db)

        deployment = repo.get_by_id(deployment_id)
        if not deployment:
            logger.error(f"Deployment not found: {deployment_id}")
            return {"status": "failed", "error": "Deployment not found"}

        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Deployment task started (task_id: {task_id})",
            level=DeploymentLogLevel.INFO,
            details={"task_id": task_id, "template_version_id": deployment.template_version_id},
        )
        repo.update_status(deployment_id, DeploymentStatus.CREATING)

        # --- Parse deployment parameters ---
        if not deployment.deployment_parameters:
            return _fail(repo, log_service, deployment_id, "No deployment_parameters found")

        try:
            deployment_params = json.loads(deployment.deployment_parameters)
            all_parameters = deployment_params.get("parameters", {})
            stack_assignments_raw = deployment_params.get("stack_assignments", [])
            teacher_info = deployment_params.get("teacher", {})
        except json.JSONDecodeError as e:
            return _fail(repo, log_service, deployment_id, f"Invalid deployment_parameters JSON: {e}")

        if not stack_assignments_raw:
            return _fail(repo, log_service, deployment_id, "No stack_assignments found")

        # --- Load template files / playbooks / etc. ---
        ctx_or_error = _load_template_context(file_service, deployment.template_version_id)
        if isinstance(ctx_or_error, str):
            return _fail(repo, log_service, deployment_id, ctx_or_error)
        template_context = ctx_or_error

        # --- Get OpenStack credentials ---
        # The OpenStack project this deployment runs against is now persisted
        # on the deployment row itself (FK), so we no longer have to derive it
        # from teacher.id and pick the first of the user's projects (which was
        # wrong whenever a user had more than one OpenstackProject row).
        openstack_project = deployment.openstack_project
        if not openstack_project:
            return _fail(
                repo, log_service, deployment_id,
                f"Deployment {deployment_id} has no openstack_project_id set",
            )

        heat_service = HeatStackService(openstack_project)

        # Ensure the Ansible keypair exists in OpenStack before creating stacks
        if get_settings().ansible_ssh_private_key:
            try:
                from src.services.ansible_keypair_service import AnsibleKeypairService
                AnsibleKeypairService.ensure_keypair(openstack_project)
            except Exception as kp_err:
                return _fail(repo, log_service, deployment_id, f"Failed to ensure Ansible keypair: {kp_err}")

        ssh_private_key = get_settings().ansible_ssh_private_key or ""

        def _ansible_factory(*, floating_ip: str, cancel_check):
            return AnsibleService(
                db=db,
                deployment_id=deployment_id,
                floating_ip=floating_ip,
                ssh_private_key=ssh_private_key,
                cancel_check=cancel_check,
            )

        created_stack_ids: list[str] = []
        failed_stacks: list[dict] = []

        for idx, stack_assignment_data in enumerate(stack_assignments_raw, start=1):
            # Cooperative cancellation checkpoint #1: between stack iterations.
            # If a DELETE arrived while we were busy with the previous stack,
            # stop creating new ones. The Heat stacks we already built were
            # persisted incrementally below, so the parallel delete task
            # picks them up from `deployment.openstack_stack_id`.
            if is_cancel_requested(db, deployment_id):
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_DELETION_REQUESTED,
                    message=(
                        f"Cancel detected before stack {idx}/{len(stack_assignments_raw)}; "
                        f"stopping after {len(created_stack_ids)} stack(s) created"
                    ),
                    level=DeploymentLogLevel.INFO,
                    details={"created_stack_ids": created_stack_ids},
                )
                return {"status": "cancelled", "stack_count": len(created_stack_ids), "stack_ids": created_stack_ids}

            stack_id: Optional[str] = None
            try:
                stack_name = _build_stack_name(deployment, idx)
                cancel_check = lambda: is_cancel_requested(db, deployment_id)  # noqa: E731

                stack_id, _instance = _provision_one_stack_assignment(
                    db=db,
                    deployment=deployment,
                    stack_assignment_data=stack_assignment_data,
                    template_context=template_context,
                    heat_service=heat_service,
                    ansible_service_factory=_ansible_factory,
                    log_service=log_service,
                    all_parameters=all_parameters,
                    teacher_info=teacher_info,
                    stack_name=stack_name,
                    stack_index=idx,
                    total_stacks=len(stack_assignments_raw),
                    cancel_check=cancel_check,
                )
                if stack_id:
                    created_stack_ids.append(stack_id)

                    # Persist the new stack ID incrementally so a parallel cancel
                    # (DELETE request → delete_deployment task) can find every
                    # Heat stack we've created so far. Without this, the cleanup
                    # would miss stacks created in later loop iterations because
                    # `openstack_stack_id` is otherwise only flushed at the very
                    # end of the task.
                    try:
                        deployment.openstack_stack_id = json.dumps(created_stack_ids)
                        db.commit()
                    except Exception as persist_err:
                        db.rollback()
                        logger.warning(
                            f"Failed to incrementally persist stack id {stack_id}: {persist_err}"
                        )

                # If cancel was observed mid-provision, the helper returned a
                # stack_id with no further work — fold the cancel up so the
                # caller doesn't keep iterating.
                if cancel_check():
                    return {"status": "cancelled", "stack_count": len(created_stack_ids), "stack_ids": created_stack_ids}
            except CancelledException as cancel_err:
                # Cancel was observed mid-SSH-wait or mid-playbook.
                # Don't escalate to FAILED — log and exit cleanly.
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_DELETION_REQUESTED,
                    message=f"Ansible phase cancelled for stack {idx}: {cancel_err}",
                    level=DeploymentLogLevel.INFO,
                    details={"created_stack_ids": created_stack_ids},
                )
                return {"status": "cancelled", "stack_count": len(created_stack_ids), "stack_ids": created_stack_ids}
            except Exception as stack_error:
                # If create_stack raised AFTER the stack was actually created
                # (CREATE_FAILED or wait timeout), it stamps the id onto the
                # exception so we can still record it for later cleanup. Without
                # this, the half-created stack would be orphaned in OpenStack
                # and the delete task wouldn't know to tear it down.
                orphan_stack_id = getattr(stack_error, "stack_id", None)
                if orphan_stack_id and orphan_stack_id not in created_stack_ids:
                    created_stack_ids.append(orphan_stack_id)
                    try:
                        deployment.openstack_stack_id = json.dumps(created_stack_ids)
                        db.commit()
                    except Exception as persist_err:
                        db.rollback()
                        logger.warning(
                            f"Failed to persist orphan stack id {orphan_stack_id}: {persist_err}"
                        )

                error_msg = f"Failed to deploy stack {idx}: {str(stack_error)}"
                logger.error(error_msg, exc_info=True)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.ANSIBLE_FAILED if stack_id else DeploymentLogEventType.FAILED,
                    message=error_msg,
                    level=DeploymentLogLevel.ERROR,
                    details={"error": str(stack_error), "stack_index": idx, "orphan_stack_id": orphan_stack_id},
                )
                failed_stacks.append({"index": idx, "error": str(stack_error)})

        # --- Store results ---
        if created_stack_ids:
            deployment.openstack_stack_id = json.dumps(created_stack_ids)
            db.commit()
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.VM_READY,
                message=f"Created {len(created_stack_ids)}/{len(stack_assignments_raw)} stacks",
                level=DeploymentLogLevel.INFO,
                details={"stack_ids": created_stack_ids, "failed_stacks": len(failed_stacks)},
            )

        if failed_stacks and not created_stack_ids:
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": f"All {len(failed_stacks)} stacks failed", "failed_stacks": failed_stacks}
        elif failed_stacks:
            # Some stacks failed (e.g. Ansible error) — mark as FAILED even if Heat succeeded
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "created_stacks": len(created_stack_ids), "failed_stacks": failed_stacks}
        else:
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)
            return {"status": "success", "stack_count": len(created_stack_ids), "stack_ids": created_stack_ids}

    except Exception as e:
        logger.exception(f"Failed to deploy stacks for deployment {deployment_id}: {e}")
        try:
            log_service = DeploymentLogService(db)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=f"Deployment failed: {str(e)}",
                level=DeploymentLogLevel.ERROR,
                details={"error": str(e), "error_type": type(e).__name__},
            )
        except Exception as log_error:
            logger.error(f"Failed to log deployment error: {log_error}")
        try:
            repo = DeploymentRepository(db)
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
        except Exception:
            pass
        return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}
    finally:
        db.close()


def _build_stack_name(deployment, stack_index: int) -> str:
    """Build a Heat-safe stack name from the deployment name + index.

    Pulled out so the redeploy path produces the same naming scheme as the
    initial deploy. Heat is allergic to spaces, underscores and >64-char
    names, so the same sanitisation rule must apply everywhere.
    """
    stack_name = f"{deployment.name}-s{stack_index}-{deployment.id[:4]}"
    return stack_name.replace(" ", "-").replace("_", "-").lower()[:64]


def _fail(repo, log_service, deployment_id: str, error_msg: str) -> dict:
    """Log error, set status to FAILED and return failure dict."""
    logger.error(error_msg)
    log_service.log(
        deployment_id=deployment_id,
        event_type=DeploymentLogEventType.FAILED,
        message=error_msg,
        level=DeploymentLogLevel.ERROR,
    )
    repo.update_status(deployment_id, DeploymentStatus.FAILED)
    return {"status": "failed", "error": error_msg}




def _gc_orphan_student_memberships(db, user_ids: set[str]) -> None:
    """Drop CourseMember / GroupMember / User rows for users that no longer
    have any deployment behind them.

    Called from ``delete_deployment`` AFTER the deployment row is gone. For
    each candidate user:
      1. Walk their CourseMember rows.
      2. For each CourseMember, count its GroupMember rows that still point
         to a course_group with at least one DeploymentInstanceAccess on any
         live DeploymentInstance. If zero remain → drop the GroupMembers and
         the CourseMember.
      3. Once a user has no CourseMember rows left, drop the User row.

    Limited to users that are pure students. The caller's
    ``DeploymentService._sync_student_memberships`` is the only place we
    auto-create User rows from a wizard payload, and only for students;
    lecturers/admins arrive via Keycloak login (UserSyncService) and
    additionally own templates / OpenStack projects, so this function
    leaves them alone via the explicit "no owner rows" guard.
    """
    if not user_ids:
        return

    from src.models.course_member import CourseMember
    from src.models.deployment_instance import DeploymentInstance
    from src.models.deployment_instance_access import DeploymentInstanceAccess
    from src.models.group_member import GroupMember
    from src.models.openstack_project import OpenstackProject
    from src.models.template import Template
    from src.models.user import User

    removed_users = 0
    removed_course_members = 0
    removed_group_members = 0

    for user_id in user_ids:
        # Guard: skip anyone who owns templates or openstack projects —
        # cannot be a pure student. This is the safety net against
        # accidentally pruning a lecturer if user_ids ever contains one.
        owns_templates = (
            db.query(Template.id).filter(Template.owner_id == user_id).first()
            is not None
        )
        owns_openstack = (
            db.query(OpenstackProject.id)
            .filter(OpenstackProject.owner_user_id == user_id)
            .first()
            is not None
        )
        if owns_templates or owns_openstack:
            continue

        course_members = db.query(CourseMember).filter(
            CourseMember.user_id == user_id
        ).all()

        for cm in course_members:
            # Which group_memberships of this course_member still point to a
            # group that has any live DeploymentInstanceAccess?
            live_group_member_ids = {
                row[0]
                for row in db.query(GroupMember.id)
                .join(
                    DeploymentInstanceAccess,
                    DeploymentInstanceAccess.group_id == GroupMember.group_id,
                )
                .join(
                    DeploymentInstance,
                    DeploymentInstance.id
                    == DeploymentInstanceAccess.deployment_instance_id,
                )
                .filter(GroupMember.course_member_id == cm.id)
                .distinct()
                .all()
            }

            stale_group_members = (
                db.query(GroupMember)
                .filter(GroupMember.course_member_id == cm.id)
                .all()
            )
            for gm in stale_group_members:
                if gm.id in live_group_member_ids:
                    continue
                db.delete(gm)
                removed_group_members += 1

            # After pruning, does this CourseMember have any live group
            # memberships left? If not, drop the CourseMember itself.
            db.flush()
            remaining = (
                db.query(GroupMember.id)
                .filter(GroupMember.course_member_id == cm.id)
                .first()
            )
            if remaining is None:
                db.delete(cm)
                removed_course_members += 1

        db.flush()
        # If no CourseMember rows survived → user is no longer tied to ANY
        # course → safe to drop. We also re-check owner relationships in case
        # something raced.
        remaining_cm = (
            db.query(CourseMember.id)
            .filter(CourseMember.user_id == user_id)
            .first()
        )
        if remaining_cm is None:
            user = db.query(User).filter(User.id == user_id).first()
            if user is not None:
                db.delete(user)
                removed_users += 1

    db.commit()
    if removed_users or removed_course_members or removed_group_members:
        logger.info(
            "Student GC complete",
            extra={
                "removed_users": removed_users,
                "removed_course_members": removed_course_members,
                "removed_group_members": removed_group_members,
                "candidates": len(user_ids),
            },
        )


@celery_app.task(bind=True)
def delete_deployment(self, deployment_id: str) -> dict:
    """Delete a deployment's OpenStack resources and remove DB record.

    This task performs the actual deletion on OpenStack and then deletes
    the deployment row from the database. It logs progress to the
    deployment logs table.
    """
    task_id = self.request.id
    logger.info(f"Starting delete task for deployment_id={deployment_id}, task_id={task_id}")

    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        log_service = DeploymentLogService(db)

        deployment = repo.get_by_id(deployment_id)
        if not deployment:
            logger.warning(f"Deployment not found for deletion: {deployment_id}")
            return {"status": "not_found", "deployment_id": deployment_id}

        # Update status to DELETING
        try:
            repo.update_status(deployment_id, DeploymentStatus.DELETING)
        except Exception:
            logger.warning("Could not set DELETING status; continuing with deletion")

        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_DELETION_REQUESTED,
            message=f"Deletion requested (task_id: {task_id})",
            level=DeploymentLogLevel.INFO,
            details={"task_id": task_id}
        )

        # If a deploy_stack task is currently in flight for this deployment,
        # it polls the status at its checkpoints (between stacks, before each
        # Ansible phase) and bails out once it sees DELETING. Give it up to
        # ~10s to flush the final created_stack_ids list to the DB before we
        # start tearing things down — otherwise we could miss a stack created
        # in the very last iteration.
        #
        # The deploy task updates status to RUNNING / FAILED / cancelled as
        # its last action; while it's still in flight the status here will
        # still read CREATING (the API set it to DELETING, and we set it to
        # DELETING again above, but a fresh deploy_stack may overwrite that
        # back to CREATING on its next status update — unlikely with the
        # current code, but harmless to handle).
        for _ in range(10):
            db.expire(deployment)
            deployment = repo.get_by_id(deployment_id)
            if deployment is None:
                break
            # Heat-stack id may have been incrementally persisted by the
            # deploy task. Pick the latest snapshot before cleanup.
            if deployment.status != DeploymentStatus.CREATING:
                break
            time.sleep(1)

        # If deployment vanished mid-wait, nothing to clean up.
        if deployment is None:
            return {"status": "already_gone", "deployment_id": deployment_id}

        # If there is an associated Heat stack, attempt to delete it
        any_stack_delete_failed = False
        if deployment.openstack_stack_id:
            try:
                # The OpenStack project is now persisted on the deployment row
                # itself (FK), so deletion always targets the project the
                # deployment was actually created in — not just the user's
                # first OpenstackProject row.
                openstack_project = deployment.openstack_project

                if not openstack_project:
                    logger.warning(
                        f"Deployment {deployment_id} has no openstack_project_id set; "
                        "skipping stack deletion"
                    )
                else:
                    heat_service = HeatStackService(openstack_project)

                    # Parse stack IDs (can be single ID or JSON array)
                    try:
                        stack_ids = json.loads(deployment.openstack_stack_id)
                        if not isinstance(stack_ids, list):
                            stack_ids = [stack_ids]
                    except (json.JSONDecodeError, TypeError):
                        # Fallback: treat as single stack ID
                        stack_ids = [deployment.openstack_stack_id]

                    logger.info(f"Deleting {len(stack_ids)} Heat stack(s)")
                    deleted_count = 0
                    surviving_stack_ids: list[str] = []
                    failed_deletions = []

                    for idx, stack_id in enumerate(stack_ids, start=1):
                        try:
                            heat_service.delete_stack(stack_id)
                            deleted_count += 1
                            logger.info(f"Heat stack {idx}/{len(stack_ids)} deleted: {stack_id}")
                        except Exception as delete_error:
                            logger.error(f"Failed to delete stack {stack_id}: {delete_error}")
                            failed_deletions.append({"stack_id": stack_id, "error": str(delete_error)})
                            surviving_stack_ids.append(stack_id)

                    log_service.log(
                        deployment_id=deployment_id,
                        event_type=DeploymentLogEventType.DEPLOYMENT_DELETED,
                        message=f"Heat stacks deleted: {deleted_count}/{len(stack_ids)} succeeded",
                        level=DeploymentLogLevel.INFO if not failed_deletions else DeploymentLogLevel.WARNING,
                        details={
                            "deleted_count": deleted_count,
                            "total_stacks": len(stack_ids),
                            "failed_deletions": failed_deletions if failed_deletions else None
                        }
                    )

                    # If any stack failed to delete, keep the DB row and the
                    # surviving stack ids so the user can retry. Removing the
                    # row would orphan the OpenStack stacks with no way to
                    # find them later.
                    if failed_deletions:
                        any_stack_delete_failed = True
                        try:
                            deployment.openstack_stack_id = json.dumps(surviving_stack_ids)
                            db.commit()
                        except Exception as persist_err:
                            db.rollback()
                            logger.warning(
                                f"Could not persist surviving stack ids: {persist_err}"
                            )
            except Exception as e:
                # Outer failure (e.g. heat_service init / connection error) —
                # also a reason to keep the DB row so the user can retry.
                any_stack_delete_failed = True
                logger.error(f"Failed to delete Heat stacks: {e}", exc_info=True)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=f"Failed to delete Heat stacks: {str(e)}",
                    level=DeploymentLogLevel.ERROR,
                    details={"error": str(e)}
                )

        # If any OpenStack stack deletion failed, bail out BEFORE wiping the
        # DB record. The deployment stays around (status FAILED) so the user
        # can retry the delete instead of being left with orphan stacks they
        # can no longer reach from the UI.
        if any_stack_delete_failed:
            try:
                repo.update_status(deployment_id, DeploymentStatus.FAILED)
            except Exception:
                logger.warning(
                    "Could not reset deployment status after partial delete failure"
                )
            return {
                "status": "stack_delete_failed",
                "deployment_id": deployment_id,
                "task_id": task_id,
            }

        # Before tearing down DB rows, collect the student users tied to this
        # deployment so we can clean them up after the deployment row is gone.
        # We snapshot user/course-member ids now — once the DeploymentInstance
        # → access → group_id chain is deleted there's no way to walk back to
        # the affected students.
        student_user_ids: set[str] = set()
        try:
            from src.models.deployment_instance import DeploymentInstance
            from src.models.deployment_instance_access import DeploymentInstanceAccess
            from src.models.group_member import GroupMember
            from src.models.course_member import CourseMember

            student_user_ids = {
                row[0]
                for row in db.query(CourseMember.user_id)
                .join(GroupMember, GroupMember.course_member_id == CourseMember.id)
                .join(
                    DeploymentInstanceAccess,
                    DeploymentInstanceAccess.group_id == GroupMember.group_id,
                )
                .join(
                    DeploymentInstance,
                    DeploymentInstance.id == DeploymentInstanceAccess.deployment_instance_id,
                )
                .filter(DeploymentInstance.deployment_id == deployment_id)
                .distinct()
                .all()
            }
        except Exception as e:
            logger.warning(
                f"Failed to snapshot student users for cleanup {deployment_id}: {e}"
            )

        # Delete logs first (before deployment record)
        try:
            log_repo = DeploymentLogRepository(db)
            logs_deleted = log_repo.delete_by_deployment_id(deployment_id)
            logger.info(f"Deleted {logs_deleted} log entries for deployment {deployment_id}")
        except Exception as e:
            logger.warning(f"Failed to delete logs for deployment {deployment_id}: {e}")

        # Delete deployment_instances (FK prevents deleting deployment record otherwise)
        try:
            from src.models.deployment_instance import DeploymentInstance
            from src.models.deployment_instance_access import DeploymentInstanceAccess
            instances = db.query(DeploymentInstance).filter(
                DeploymentInstance.deployment_id == deployment_id
            ).all()
            for inst in instances:
                db.query(DeploymentInstanceAccess).filter(
                    DeploymentInstanceAccess.deployment_instance_id == inst.id
                ).delete(synchronize_session=False)
            db.query(DeploymentInstance).filter(
                DeploymentInstance.deployment_id == deployment_id
            ).delete(synchronize_session=False)
            db.commit()
            logger.info(f"Deleted {len(instances)} deployment instance(s) for {deployment_id}")
        except Exception as e:
            logger.warning(f"Failed to delete deployment instances for {deployment_id}: {e}")
            db.rollback()

        # Finally delete DB record
        try:
            deleted = repo.delete(UUID(deployment_id))
            if deleted:
                logger.info(f"Deployment record deleted from database: {deployment_id}")
            else:
                logger.warning(f"Deployment record not found when attempting delete: {deployment_id}")
        except Exception as e:
            logger.error(f"Failed to delete deployment record {deployment_id}: {e}", exc_info=True)

        # Garbage-collect student users + course/group memberships that no
        # longer have ANY deployment behind them. Rationale:
        #   * Students don't own templates or OpenStack projects (only lecturers
        #     /admins do), so a user with no remaining CourseMember rows is
        #     guaranteed to be a former student.
        #   * Each course_member -> group_member chain that survives here would
        #     otherwise live forever, growing the membership tables monotonically.
        # We re-query the surviving access rows (across ALL other deployments)
        # to decide what's safe to drop — a student in two deployments stays
        # until the second one is also deleted.
        try:
            _gc_orphan_student_memberships(db, student_user_ids)
        except Exception as e:
            logger.warning(
                f"Student cleanup failed for deployment {deployment_id}: {e}",
                exc_info=True,
            )
            db.rollback()

        return {"status": "deleted", "deployment_id": deployment_id, "task_id": task_id}

    except Exception as e:
        logger.exception(f"Error during delete task for deployment {deployment_id}: {e}")
        return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True)
def restart_deployment(self, deployment_id: str) -> dict:
    """Restart a deployment by updating the Heat stack.

    This task restarts an existing deployment by triggering a Heat stack update,
    which can restart VMs or refresh the stack configuration.

    Args:
        deployment_id: ID of the deployment to restart

    Returns:
        Result dictionary with status and task information
    """
    task_id = self.request.id
    logger.info(f"Starting restart task for deployment_id={deployment_id}, task_id={task_id}")

    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        log_service = DeploymentLogService(db)

        deployment = repo.get_by_id(deployment_id)

        if not deployment:
            logger.error(f"Deployment not found: {deployment_id}")
            return {"status": "failed", "error": "Deployment not found"}

        # Update status to RESTARTING
        repo.update_status(deployment_id, DeploymentStatus.RESTARTING)

        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Restart requested (task_id: {task_id})",
            level=DeploymentLogLevel.INFO,
            details={"task_id": task_id}
        )

        # Verify deployment has a stack
        if not deployment.openstack_stack_id:
            error_msg = "No OpenStack stack associated with this deployment"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}

        # Get OpenStack project from the deployment's persisted FK. Previously
        # this was re-derived from teacher.id at every read site and picked the
        # user's first OpenstackProject row, which broke whenever a user had
        # more than one (clouds.yaml switch scenario).
        openstack_project = deployment.openstack_project

        if not openstack_project:
            error_msg = f"Deployment {deployment_id} has no openstack_project_id set"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}

        try:
            heat_service = HeatStackService(openstack_project)

            # Trigger stack update to restart resources
            logger.info(f"Updating Heat stack {deployment.openstack_stack_id} to trigger restart")
            heat_service.update_stack(deployment.openstack_stack_id)

            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message=f"Heat stack update initiated for restart: {deployment.openstack_stack_id}",
                level=DeploymentLogLevel.INFO,
                details={"stack_id": deployment.openstack_stack_id}
            )

            # Update status back to RUNNING (stack update is async in OpenStack)
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)

            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message="Restart completed successfully",
                level=DeploymentLogLevel.INFO
            )

            return {
                "status": "restarted",
                "deployment_id": deployment_id,
                "stack_id": deployment.openstack_stack_id,
                "task_id": task_id
            }

        except Exception as e:
            error_msg = f"Failed to restart deployment: {str(e)}"
            logger.exception(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR,
                details={"error": str(e)}
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}

    except Exception as e:
        logger.exception(f"Error during restart task for deployment {deployment_id}: {e}")
        return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Redeploy paths
# ---------------------------------------------------------------------------


def _merge_parameter_layers(
    *,
    base: dict[str, Any],
    deployment_overrides: dict[str, Any] | None,
    instance_overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge parameter layers for a redeploy.

    Order — later layers win::

        base (deployment.deployment_parameters['parameters'])
            ↓
        deployment_overrides (apply to every VM)
            ↓
        instance_overrides (apply to THIS one VM)

    Shallow merge by design — template parameters are flat key/value
    pairs (per the app.yaml contract). Nested dicts in a parameter value
    are replaced, not deep-merged, mirroring how the wizard treats them.
    """
    merged = dict(base)
    if deployment_overrides:
        merged.update(deployment_overrides)
    if instance_overrides:
        merged.update(instance_overrides)
    return merged


def _snapshot_instance_credentials(
    db, instance: DeploymentInstance
) -> dict[str, Any]:
    """Read ``DeploymentInstanceAccess`` rows back into a ``generated``-shaped
    dict so the redeploy task can reuse them when ``preserve_credentials=True``.

    Round-tripping the rows back into the ``generated`` shape is intrinsically
    lossy — ``_build_user_json``'s ``applications[]`` block was originally
    keyed by app.yaml credential type (``postgres``, ``pgadmin``, …), but
    once persisted it lives under a single ``DATABASE`` ``AccessType`` row
    that merges them. We can't recover the original app name. The snapshot
    therefore carries the access rows verbatim under a single ``_preserved_access``
    list per group; ``_rebind_preserved_access_rows`` (called AFTER the new
    instance is persisted) then re-points the old rows at the new instance,
    keeping the port / connection_url / ssh_private_key fields intact.

    Why not regenerate via the ``generated`` dict + Ansible:
      * Server never persists ``ssh_key.public_key`` — re-emitting an empty
        public_key would break authorized_keys on the new VM.
      * Non-SSH rows lose port / connection_url under the access-type roundtrip.
      * Ansible playbooks generate their own per-VM passwords; injecting the
        OLD password into extra_vars doesn't actually keep students' logins
        working unless the playbook is idempotent about it.

    Returns a dict with two keys (both consumed only inside this module):
      * ``_preserved_access``: list of dicts holding every column of each
        DeploymentInstanceAccess row, ready for the rebind step.
      * ``deployment_groups`` / ``teacher``: kept empty — credentials are
        rebound from access rows, NOT pumped through user_json.
    """
    # Capture all columns we need to rehydrate the access row against the new
    # instance. Fernet-encrypted columns (password, ssh_private_key) are
    # decrypted transparently on read via EncryptedString; we re-encrypt on
    # the new INSERT.
    preserved: list[dict[str, Any]] = []
    for access in list(instance.access_methods or []):
        preserved.append({
            "access_type": access.access_type,
            "group_id": access.group_id,
            "connection_url": access.connection_url,
            "username": access.username,
            "password": access.password,
            "ssh_private_key": access.ssh_private_key,
            "port": access.port,
            "is_active": access.is_active,
            "expires_at": access.expires_at,
        })

    return {
        "_preserved_access": preserved,
        "deployment_groups": [],
        "teacher": {},
    }


def _rebind_preserved_access_rows(
    db,
    new_instance: DeploymentInstance,
    preserved_user_json: dict[str, Any],
) -> int:
    """Recreate access rows from a snapshot under the new instance's id.

    Companion to :func:`_snapshot_instance_credentials`. ``persist_credentials_for_stack``
    already wrote freshly-generated access rows for the new instance — we drop
    those and replace with the preserved set so port / connection_url / SSH
    private key persist verbatim across the redeploy.

    Returns the number of preserved rows written.
    """
    preserved = (preserved_user_json or {}).get("_preserved_access") or []
    if not preserved:
        return 0

    # Drop the just-generated access rows for the new instance — they're
    # superseded by the snapshot.
    db.query(DeploymentInstanceAccess).filter(
        DeploymentInstanceAccess.deployment_instance_id == new_instance.id
    ).delete(synchronize_session=False)

    written = 0
    for row in preserved:
        db.add(
            DeploymentInstanceAccess(
                deployment_instance_id=new_instance.id,
                access_type=row["access_type"],
                group_id=row.get("group_id"),
                connection_url=row.get("connection_url"),
                username=row.get("username"),
                password=row.get("password"),
                ssh_private_key=row.get("ssh_private_key"),
                port=row.get("port"),
                is_active=row.get("is_active", True),
                expires_at=row.get("expires_at"),
            )
        )
        written += 1
    db.commit()
    return written


def _delete_single_instance_resources(
    *,
    db,
    deployment,
    instance: DeploymentInstance,
    heat_service: HeatStackService,
    log_service: DeploymentLogService,
) -> tuple[bool, list[str]]:
    """Tear down the Heat stack for ONE instance and clean its DB rows.

    Mirrors the relevant slice of ``delete_deployment`` but for a single
    instance, not the whole deployment. Returns ``(success, remaining_stack_ids)``:
      * ``success`` is False when Heat refused to delete the stack — in
        that case the row is intentionally NOT removed (so the user can
        retry), and the parent deployment.openstack_stack_id keeps the
        surviving id so a future cleanup can pick it up.
      * ``remaining_stack_ids`` is the updated stack-id list for the
        parent deployment (caller persists it).
    """
    deployment_id = deployment.id
    stack_id = instance.openstack_server_id  # Heat stack id, same column

    # Parse the deployment's stack-id JSON array so we can rewrite it
    # after the per-instance delete.
    try:
        stack_ids = json.loads(deployment.openstack_stack_id or "[]")
        if not isinstance(stack_ids, list):
            stack_ids = [stack_ids]
    except (json.JSONDecodeError, TypeError):
        stack_ids = [deployment.openstack_stack_id] if deployment.openstack_stack_id else []

    if stack_id:
        try:
            heat_service.delete_stack(stack_id)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_DELETED,
                message=f"Redeploy: Heat stack deleted: {stack_id}",
                level=DeploymentLogLevel.INFO,
                details={"stack_id": stack_id, "instance_id": instance.id},
            )
        except Exception as delete_error:
            logger.error(
                f"Redeploy: failed to delete stack {stack_id} for instance {instance.id}: {delete_error}",
                exc_info=True,
            )
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=f"Redeploy: failed to delete Heat stack {stack_id}: {delete_error}",
                level=DeploymentLogLevel.ERROR,
                details={"stack_id": stack_id, "instance_id": instance.id, "error": str(delete_error)},
            )
            return False, stack_ids

        # Pull the deleted id out of the deployment's stack-id list.
        stack_ids = [sid for sid in stack_ids if sid != stack_id]

    # Wipe access rows + the instance row itself; the new instance will
    # be persisted by the provisioning helper afterwards.
    try:
        db.query(DeploymentInstanceAccess).filter(
            DeploymentInstanceAccess.deployment_instance_id == instance.id
        ).delete(synchronize_session=False)
        db.delete(instance)
        db.flush()
    except Exception as wipe_err:
        logger.error(
            f"Redeploy: failed to delete DB rows for instance {instance.id}: {wipe_err}",
            exc_info=True,
        )
        db.rollback()
        return False, stack_ids

    return True, stack_ids


def _build_redeploy_stack_name(deployment, stack_index: int, instance_id: str) -> str:
    """Like :func:`_build_stack_name` but with a per-redeploy suffix to avoid
    colliding with the OLD stack still in DELETE_IN_PROGRESS on Heat.

    ``heat_service.delete_stack`` returns as soon as Heat ACK's the request;
    the actual stack tear-down (VMs / volumes / floating-IPs) takes 30-120 s
    on a busy region. If we tried to ``create_stack`` with the same name
    immediately, Heat would reject it with "Stack already exists". We suffix
    with ``-r<8-hex-of-old-instance-id>`` — deterministic per redeploy,
    short enough not to blow the 64-char cap, and stable across retries of
    the same task so an Ansible-only re-run doesn't accidentally fork
    another stack.

    The new name is what gets persisted into ``DeploymentInstance.vm_name``,
    so the original ``-s{idx}-`` slug stays inside the name and remains
    parseable by :func:`_recover_stack_index_for_instance`.
    """
    # Strip dashes so the suffix is compact and only hex chars survive (the
    # regex used to recover stack_index allows [a-f0-9]+ after the index).
    suffix = instance_id.replace("-", "")[:8].lower()
    base = f"{deployment.name}-s{stack_index}-{deployment.id[:4]}-r{suffix}"
    return base.replace(" ", "-").replace("_", "-").lower()[:64]


def _recover_stack_assignment_and_index(
    instance: DeploymentInstance,
    stack_assignments_raw: list[dict],
    db=None,
) -> tuple[dict | None, int | None]:
    """Recover the (stack_assignment, 1-based stack_index) tuple for an
    instance. Single source of truth for the regex + fallback so the two
    pieces of state can't drift.

    Resolution order:
      1. Regex on ``vm_name`` for the original ``-s<idx>-`` slug. This is
         the cheap path; nothing else needs to happen when the name survived
         unmodified.
      2. ``StackAssignment.stack_index`` — the wizard payload itself carries
         the 1-based index for each assignment, so we can look up by it.
      3. Fallback: position of this instance among its deployment siblings
         when sorted by ``created_at``. This matches the order in which
         ``deploy_stack`` iterates ``stack_assignments`` (sequential, no
         concurrency), so the Nth-created instance corresponds to the Nth
         assignment. Only used when ``db`` is supplied.

    Returns ``(None, None)`` if all three paths fail.
    """
    import re

    idx_one_based: int | None = None
    if instance.vm_name:
        match = re.search(r"-s(\d+)-[a-f0-9]+", instance.vm_name)
        if match:
            idx_one_based = int(match.group(1))

    # If the regex worked, try to match the assignment by its stack_index field
    # first (most reliable), then fall back to positional index.
    if idx_one_based is not None:
        for assignment in stack_assignments_raw:
            if isinstance(assignment, dict) and assignment.get("stack_index") == idx_one_based:
                return assignment, idx_one_based
        if 0 <= idx_one_based - 1 < len(stack_assignments_raw):
            return stack_assignments_raw[idx_one_based - 1], idx_one_based
        # vm_name parsed but no matching assignment (e.g. empty list, or a
        # malformed deployment_parameters). Hold onto the parsed index so the
        # logging fallback (_stack_index_for_instance) is still useful, but
        # signal "no assignment recovered" via the None on the first tuple slot.
        return None, idx_one_based

    # Final fallback: positional match by created_at among siblings. Only
    # works when we have a session and there's at least one assignment.
    if db is not None and stack_assignments_raw:
        siblings = (
            db.query(DeploymentInstance.id)
            .filter(DeploymentInstance.deployment_id == instance.deployment_id)
            .order_by(DeploymentInstance.created_at.asc())
            .all()
        )
        ordered_ids = [row[0] for row in siblings]
        try:
            pos = ordered_ids.index(instance.id)
        except ValueError:
            pos = -1
        if 0 <= pos < len(stack_assignments_raw):
            idx_one_based = pos + 1
            return stack_assignments_raw[pos], idx_one_based

    return None, None


def _reconstruct_stack_assignment_for_instance(
    instance: DeploymentInstance,
    stack_assignments_raw: list[dict],
) -> dict | None:
    """Back-compat shim around :func:`_recover_stack_assignment_and_index`.

    Kept for the unit tests that exercise the vm_name parse in isolation
    (``tests/unit/test_redeploy_tasks.py``). New callers should use
    :func:`_recover_stack_assignment_and_index` so the index + assignment
    come back together (no second regex pass).
    """
    assignment, _ = _recover_stack_assignment_and_index(instance, stack_assignments_raw)
    return assignment


def _stack_index_for_instance(
    instance: DeploymentInstance,
    stack_assignments_raw: list[dict],
) -> int:
    """Back-compat shim around :func:`_recover_stack_assignment_and_index`.

    Returns the 1-based index recovered from vm_name, or 1 as a last-resort
    fallback. New code in this module should call the combined helper.
    """
    _, idx = _recover_stack_assignment_and_index(instance, stack_assignments_raw)
    return idx if idx is not None else 1


@celery_app.task(bind=True)
def redeploy_instance(
    self,
    deployment_id: str,
    instance_id: str,
    deployment_parameter_overrides: dict | None = None,
    preserve_credentials: bool = False,
) -> dict:
    """Destroy-and-recreate a single ``DeploymentInstance`` (= one VM).

    The parent deployment stays in ``RUNNING`` so its siblings remain
    reachable. Only the targeted instance flips to ``REDEPLOYING`` for the
    duration of the task. On success the old row is dropped and a fresh
    one (new credentials by default) takes its place; on failure the row
    flips to ``FAILED`` and the deployment.openstack_stack_id is rewritten
    to reflect surviving stacks (so a future delete cleans up correctly).

    Heat naming is preserved (same ``-s{idx}-{dep4}`` slug) so the new
    stack looks identical to a fresh deploy in the OpenStack tags.

    Args:
        deployment_id: Parent deployment ID.
        instance_id: ID of the ``DeploymentInstance`` row to recreate.
        deployment_parameter_overrides: Optional overrides merged on top
            of the deployment's stored parameters before splitting into
            Heat / Ansible.
        preserve_credentials: When True, reuse the existing access rows
            on the new instance instead of regenerating. Default False.
    """
    task_id = self.request.id
    logger.info(
        f"Starting redeploy_instance task for deployment_id={deployment_id} "
        f"instance_id={instance_id} task_id={task_id}"
    )

    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        log_service = DeploymentLogService(db)
        file_service = TemplateVersionFileService(db)

        deployment = repo.get_by_id(deployment_id)
        if not deployment:
            return {"status": "failed", "error": "Deployment not found"}

        instance = (
            db.query(DeploymentInstance)
            .filter(
                DeploymentInstance.id == instance_id,
                DeploymentInstance.deployment_id == deployment_id,
            )
            .first()
        )
        if not instance:
            return {"status": "failed", "error": f"Instance {instance_id} not found"}

        instance.status = DeploymentInstanceStatus.REDEPLOYING
        db.commit()

        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=(
                f"Redeploying instance {instance.vm_name or instance_id} "
                f"(task_id: {task_id}, preserve_credentials={preserve_credentials})"
            ),
            level=DeploymentLogLevel.INFO,
            details={
                "task_id": task_id,
                "instance_id": instance_id,
                "preserve_credentials": preserve_credentials,
                "overrides": deployment_parameter_overrides or {},
            },
        )

        # --- Parse deployment parameters ---
        if not deployment.deployment_parameters:
            return _fail_instance(repo, log_service, db, deployment_id, instance, "No deployment_parameters found")

        try:
            deployment_params = json.loads(deployment.deployment_parameters)
            base_parameters = deployment_params.get("parameters", {})
            stack_assignments_raw = deployment_params.get("stack_assignments", [])
            teacher_info = deployment_params.get("teacher", {})
        except json.JSONDecodeError as e:
            return _fail_instance(repo, log_service, db, deployment_id, instance, f"Invalid deployment_parameters JSON: {e}")

        # Recover the stack assignment + index that produced THIS instance
        # via the consolidated helper (regex first, positional fallback) so
        # both pieces come from the same source — no risk of one returning
        # None while the other defaults to 1.
        stack_assignment_data, stack_idx = _recover_stack_assignment_and_index(
            instance, stack_assignments_raw, db=db,
        )
        if stack_assignment_data is None or stack_idx is None:
            return _fail_instance(
                repo, log_service, db, deployment_id, instance,
                f"Cannot recover stack_assignment for instance {instance_id} (vm_name={instance.vm_name!r})",
            )

        # Load template once.
        ctx_or_error = _load_template_context(file_service, deployment.template_version_id)
        if isinstance(ctx_or_error, str):
            return _fail_instance(repo, log_service, db, deployment_id, instance, ctx_or_error)
        template_context = ctx_or_error

        # Optionally snapshot existing credentials before we wipe the access rows.
        preserved_user_json = (
            _snapshot_instance_credentials(db, instance) if preserve_credentials else None
        )

        openstack_project = deployment.openstack_project
        if not openstack_project:
            return _fail_instance(
                repo, log_service, db, deployment_id, instance,
                f"Deployment {deployment_id} has no openstack_project_id set",
            )

        heat_service = HeatStackService(openstack_project)

        # --- 1. Delete the old Heat stack + DB rows for this instance ---
        ok, remaining_stack_ids = _delete_single_instance_resources(
            db=db,
            deployment=deployment,
            instance=instance,
            heat_service=heat_service,
            log_service=log_service,
        )
        if not ok:
            # _delete_single_instance_resources already logged; flip instance
            # to FAILED (it may still be in DB if the wipe failed) and bail.
            try:
                # If the instance row is still around, mark it FAILED.
                still_there = db.query(DeploymentInstance).filter(
                    DeploymentInstance.id == instance_id
                ).first()
                if still_there:
                    still_there.status = DeploymentInstanceStatus.FAILED
                    db.commit()
            except Exception:
                db.rollback()
            return {
                "status": "failed",
                "deployment_id": deployment_id,
                "instance_id": instance_id,
                "error": "Failed to delete old Heat stack / DB rows",
            }

        # Persist the rewritten stack-id list so a parallel delete sees it.
        try:
            deployment.openstack_stack_id = json.dumps(remaining_stack_ids)
            db.commit()
        except Exception as persist_err:
            db.rollback()
            logger.warning(f"Failed to persist remaining stack ids: {persist_err}")

        # --- 2. Recreate the stack with merged parameters ---
        if get_settings().ansible_ssh_private_key:
            try:
                from src.services.ansible_keypair_service import AnsibleKeypairService
                AnsibleKeypairService.ensure_keypair(openstack_project)
            except Exception as kp_err:
                # The old instance row is already gone; emit a placeholder
                # FAILED row carrying the deployment + course_group_id so the
                # UI still shows "1 of N VMs broken" rather than silently
                # shrinking the class roster.
                _record_redeploy_failure_placeholder(
                    db=db,
                    deployment_id=deployment_id,
                    old_instance_id=instance_id,
                    stack_index=stack_idx,
                    log_service=log_service,
                    error_msg=f"Failed to ensure Ansible keypair: {kp_err}",
                )
                return {
                    "status": "failed",
                    "deployment_id": deployment_id,
                    "instance_id": instance_id,
                    "error": f"Failed to ensure Ansible keypair: {kp_err}",
                }

        ssh_private_key = get_settings().ansible_ssh_private_key or ""

        def _ansible_factory(*, floating_ip: str, cancel_check):
            return AnsibleService(
                db=db,
                deployment_id=deployment_id,
                floating_ip=floating_ip,
                ssh_private_key=ssh_private_key,
                cancel_check=cancel_check,
            )

        merged_params = _merge_parameter_layers(
            base=base_parameters,
            deployment_overrides=deployment_parameter_overrides,
            instance_overrides=None,
        )
        # Use a redeploy-suffixed name to avoid colliding with the OLD stack
        # that Heat may still be tearing down (delete_stack is async).
        stack_name = _build_redeploy_stack_name(deployment, stack_idx, instance_id)

        try:
            new_stack_id, new_instance = _provision_one_stack_assignment(
                db=db,
                deployment=deployment,
                stack_assignment_data=stack_assignment_data,
                template_context=template_context,
                heat_service=heat_service,
                ansible_service_factory=_ansible_factory,
                log_service=log_service,
                all_parameters=merged_params,
                teacher_info=teacher_info,
                stack_name=stack_name,
                stack_index=stack_idx,
                total_stacks=1,
                cancel_check=None,
                preserved_user_json=preserved_user_json,
            )
        except Exception as e:
            logger.exception(f"Redeploy of instance {instance_id} failed: {e}")
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=f"Redeploy failed: {e}",
                level=DeploymentLogLevel.ERROR,
                details={"instance_id": instance_id, "error": str(e)},
            )
            # An orphan stack id may have been stamped onto the exception by
            # the Heat service (CREATE_FAILED / timeout) or by the credential
            # persist step (which keeps the stack id alive so the user can
            # retry). Add it back to the deployment so a future delete cleans
            # up rather than silently leaking the stack.
            orphan = getattr(e, "stack_id", None)
            if orphan:
                remaining_stack_ids.append(orphan)
                try:
                    deployment.openstack_stack_id = json.dumps(remaining_stack_ids)
                    db.commit()
                except Exception:
                    db.rollback()
            # Make sure the deployment still has a placeholder DeploymentInstance
            # row visible — the old row is gone and (depending on where the
            # exception hit) the new one may never have been persisted.
            _record_redeploy_failure_placeholder(
                db=db,
                deployment_id=deployment_id,
                old_instance_id=instance_id,
                stack_index=stack_idx,
                log_service=log_service,
                error_msg=str(e),
            )
            return {
                "status": "failed",
                "deployment_id": deployment_id,
                "instance_id": instance_id,
                "error": str(e),
            }

        # Persist the new stack id back onto the parent deployment.
        if new_stack_id:
            remaining_stack_ids.append(new_stack_id)
            try:
                deployment.openstack_stack_id = json.dumps(remaining_stack_ids)
                db.commit()
            except Exception as persist_err:
                db.rollback()
                logger.warning(
                    f"Failed to persist redeployed stack id {new_stack_id}: {persist_err}"
                )

        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.VM_READY,
            message=f"Redeploy completed for instance {new_instance.id if new_instance else instance_id}",
            level=DeploymentLogLevel.INFO,
            details={
                "old_instance_id": instance_id,
                "new_instance_id": new_instance.id if new_instance else None,
                "new_stack_id": new_stack_id,
            },
        )

        # Normalise the parent deployment status — when a previously-FAILED
        # deployment was recovered via per-instance redeploy, the row should
        # come back to RUNNING. Other statuses (CREATING/DELETING/RESTARTING)
        # were already gated out by the endpoint, so a redeploy never sees
        # them mid-flight.
        try:
            if deployment.status != DeploymentStatus.RUNNING:
                repo.update_status(deployment_id, DeploymentStatus.RUNNING)
        except Exception as status_err:
            logger.warning(
                f"Could not normalise deployment status after redeploy_instance: {status_err}"
            )

        return {
            "status": "redeployed",
            "deployment_id": deployment_id,
            "old_instance_id": instance_id,
            "new_instance_id": new_instance.id if new_instance else None,
            "new_stack_id": new_stack_id,
            "task_id": task_id,
        }

    except Exception as e:
        logger.exception(f"Error during redeploy_instance task for {instance_id}: {e}")
        return {"status": "failed", "deployment_id": deployment_id, "instance_id": instance_id, "error": str(e)}
    finally:
        db.close()


def _fail_instance(
    repo: DeploymentRepository,
    log_service: DeploymentLogService,
    db,
    deployment_id: str,
    instance: DeploymentInstance | None,
    error_msg: str,
) -> dict:
    """Log + flip a single instance to FAILED without touching the
    parent deployment's status (siblings should stay reachable)."""
    logger.error(error_msg)
    log_service.log(
        deployment_id=deployment_id,
        event_type=DeploymentLogEventType.FAILED,
        message=error_msg,
        level=DeploymentLogLevel.ERROR,
        details={"instance_id": instance.id if instance else None},
    )
    if instance is not None:
        try:
            instance.status = DeploymentInstanceStatus.FAILED
            db.commit()
        except Exception:
            db.rollback()
    return {"status": "failed", "error": error_msg, "deployment_id": deployment_id}


def _record_redeploy_failure_placeholder(
    *,
    db,
    deployment_id: str,
    old_instance_id: str,
    stack_index: int,
    log_service: DeploymentLogService,
    error_msg: str,
) -> None:
    """Insert a placeholder ``DeploymentInstance(status=FAILED)`` after a
    mid-redeploy crash that left the deployment with no row for this slot.

    By the time we reach this helper the OLD instance has already been
    deleted from the DB (and its Heat stack from OpenStack), and the new
    one may or may not have been persisted before the failure hit. Without
    a placeholder the deployment silently shrinks — the lecturer sees one
    fewer VM in the dashboard with no obvious link back to the failed
    redeploy. The placeholder keeps the count stable, surfaces the error
    via the deployment-logs API, and gives the operator a clear retry target.

    No-op if a row for ``old_instance_id`` is somehow still around (e.g.
    rollback un-deleted it) or if a new row was already persisted in the
    same task — we never want to double-write.
    """
    try:
        existing = (
            db.query(DeploymentInstance)
            .filter(DeploymentInstance.id == old_instance_id)
            .first()
        )
        if existing is not None:
            # Old row survived (rollback or duplicate path) — just flip its
            # status rather than inserting a sibling.
            existing.status = DeploymentInstanceStatus.FAILED
            db.commit()
            return

        # Create a fresh row. We don't know the new Heat stack id; leave
        # openstack_server_id NULL so future delete_deployment doesn't try
        # to tear down a non-existent stack. The vm_name records which
        # slot failed so it shows up in the UI in roughly the right place.
        from uuid import uuid4
        placeholder = DeploymentInstance(
            id=str(uuid4()),
            deployment_id=deployment_id,
            vm_name=f"redeploy-failed-s{stack_index}",
            openstack_server_id=None,
            status=DeploymentInstanceStatus.FAILED,
        )
        db.add(placeholder)
        db.commit()
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.FAILED,
            message=(
                f"Redeploy left stack #{stack_index} without a DB row; "
                "wrote a FAILED placeholder so the slot stays visible."
            ),
            level=DeploymentLogLevel.WARNING,
            details={
                "old_instance_id": old_instance_id,
                "placeholder_id": placeholder.id,
                "stack_index": stack_index,
                "error": error_msg,
            },
        )
    except Exception as placeholder_err:
        # Last resort — the placeholder is itself best-effort. Log and let
        # the surrounding return run; the operator still has the log row
        # explaining what failed.
        logger.error(
            f"Failed to record redeploy-failure placeholder for {old_instance_id}: {placeholder_err}",
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass


@celery_app.task(bind=True)
def redeploy_deployment(
    self,
    deployment_id: str,
    deployment_parameter_overrides: dict | None = None,
    instance_parameter_overrides: dict | None = None,
    preserve_credentials: bool = False,
) -> dict:
    """Redeploy every VM in a deployment, one after another.

    Sequential by design — the parent OpenStack project has finite quota,
    so fan-out would risk a quota exhaustion mid-class. The deployment
    stays ``RUNNING`` between instances (only the targeted one flips to
    REDEPLOYING) so the UI shows per-VM progress instead of "everything
    rebooting".

    The endpoint accepts both a deployment-wide override map and a
    per-instance map (keyed by ``DeploymentInstance.id``). For each
    instance the redeploy merges:

        base (deployment.deployment_parameters['parameters'])
            + deployment_parameter_overrides
            + instance_parameter_overrides.get(instance_id, {})

    and recreates that one VM via :func:`redeploy_instance`'s logic.
    """
    task_id = self.request.id
    logger.info(
        f"Starting redeploy_deployment task for deployment_id={deployment_id} task_id={task_id}"
    )

    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        deployment = repo.get_by_id(deployment_id)
        if not deployment:
            return {"status": "failed", "error": "Deployment not found"}

        instances = list(
            db.query(DeploymentInstance)
            .filter(DeploymentInstance.deployment_id == deployment_id)
            .order_by(DeploymentInstance.created_at.asc())
            .all()
        )
        if not instances:
            return {"status": "failed", "error": "Deployment has no instances to redeploy"}

        # Snapshot instance IDs now — the per-instance redeploy deletes
        # the row and creates a new one, which would invalidate any
        # ORM-bound list mid-iteration.
        instance_ids = [inst.id for inst in instances]
    finally:
        db.close()

    results: list[dict] = []
    overall_status = "redeployed"
    for inst_id in instance_ids:
        per_instance_overrides = (instance_parameter_overrides or {}).get(inst_id)
        # The per-instance task merges its own params on top — pass the
        # per-VM overrides folded into the deployment-wide map for this call.
        # We DON'T pass instance_parameter_overrides through to redeploy_instance
        # itself because each call already targets one VM.
        merged_dep_overrides = _merge_parameter_layers(
            base={},
            deployment_overrides=deployment_parameter_overrides,
            instance_overrides=per_instance_overrides,
        )
        # Wrap the inner call: redeploy_instance is expected to return a
        # dict on every code path, but a future regression (or a SQLAlchemy
        # error escaping its outer try) must NOT abandon the loop mid-class.
        # Without this, instances we never touched are silently skipped,
        # the aggregated result is lost, and the operator only sees a generic
        # Celery failure.
        try:
            result = redeploy_instance.run(
                deployment_id=deployment_id,
                instance_id=inst_id,
                deployment_parameter_overrides=merged_dep_overrides or None,
                preserve_credentials=preserve_credentials,
            )
        except Exception as inner_err:
            logger.exception(
                f"redeploy_instance.run raised for instance {inst_id}; "
                "continuing with remaining instances"
            )
            result = {
                "status": "failed",
                "deployment_id": deployment_id,
                "instance_id": inst_id,
                "error": f"unhandled exception: {inner_err}",
            }
        results.append(result)
        if result.get("status") != "redeployed":
            overall_status = "partial_failure"

    # Normalise the parent deployment's status on success: if it was in
    # FAILED (e.g. recovery flow via redeploy), bring it back to RUNNING.
    # On partial_failure we leave the status alone — the per-instance rows
    # already carry FAILED markers and the operator may want to retry.
    if overall_status == "redeployed":
        finalize_db = SessionLocal()
        try:
            finalize_repo = DeploymentRepository(finalize_db)
            finalize_dep = finalize_repo.get_by_id(deployment_id)
            if finalize_dep is not None and finalize_dep.status != DeploymentStatus.RUNNING:
                finalize_repo.update_status(deployment_id, DeploymentStatus.RUNNING)
        except Exception as status_err:
            logger.warning(
                f"Could not normalise deployment status to RUNNING after redeploy: {status_err}"
            )
        finally:
            finalize_db.close()

    return {
        "status": overall_status,
        "deployment_id": deployment_id,
        "task_id": task_id,
        "instance_results": results,
    }
