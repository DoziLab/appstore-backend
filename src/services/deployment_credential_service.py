"""Persist deployment credentials produced by the per-stack ``user_json``."""
from __future__ import annotations

import logging
from typing import Any
from sqlalchemy.orm import Session

from src.models.deployment_instance import DeploymentInstance, DeploymentInstanceStatus
from src.models.deployment_instance_access import AccessType, DeploymentInstanceAccess

logger = logging.getLogger(__name__)


class DeploymentCredentialService:

    def __init__(self, db: Session):
        self.db = db

    def persist_credentials_for_stack(
        self,
        deployment_id: str,
        stack_name: str,
        openstack_stack_id: str,
        user_json: dict[str, Any],
        floating_ip: str = "",
        heat_outputs: dict[str, Any] | None = None,
        flavor: str | None = None,
    ) -> DeploymentInstance:
        instance = DeploymentInstance(
            deployment_id=deployment_id,
            vm_name=stack_name,
            openstack_server_id=openstack_stack_id,
            flavor=flavor,
            status=DeploymentInstanceStatus.RUNNING,
        )
        self.db.add(instance)
        self.db.flush()

        for entry in self._extract_access_entries(user_json, floating_ip, heat_outputs or {}):
            self.db.add(
                DeploymentInstanceAccess(
                    deployment_instance_id=instance.id,
                    access_type=entry["access_type"],
                    username=entry.get("username"),
                    password=entry.get("password"),
                    ssh_private_key=entry.get("ssh_private_key"),
                    # group_id is None for admin credentials (teacher) and for
                    # legacy callers that didn't pass course_group_id. Students
                    # can only see rows with a non-NULL group_id matching one
                    # of their group memberships — see src/api/student.py.
                    group_id=entry.get("group_id"),
                    connection_url=entry.get("connection_url"),
                    port=entry.get("port"),
                )
            )

        self.db.commit()
        return instance

    @staticmethod
    def _extract_access_entries(
        user_json: dict[str, Any],
        floating_ip: str = "",
        heat_outputs: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        heat_outputs = heat_outputs or {}

        # SSH credentials (Ubuntu/Ansible templates)
        instance = user_json.get("instance") or {}
        for cred in instance.get("credentials") or []:
            username = cred.get("username")
            entries.append({
                "access_type": AccessType.SSH,
                "username": username,
                "password": cred.get("password"),
                "ssh_private_key": cred.get("ssh_private_key"),
                # ``group_id`` stamps the access row with the CourseGroup it
                # belongs to so student-self-service can filter by membership.
                # Omitted for legacy callers → row stays NULL → invisible to students.
                "group_id": cred.get("group_id"),
                "connection_url": f"ssh {username}@{floating_ip}" if username and floating_ip else None,
                "port": 22,
            })
        admin = instance.get("admin_credentials")
        if admin:
            username = admin.get("username")
            entries.append({
                "access_type": AccessType.SSH,
                "username": username,
                "password": admin.get("password"),
                "ssh_private_key": admin.get("ssh_private_key"),
                # Admin (teacher) credentials are intentionally NOT tied to a
                # group — group_id stays NULL so students never see them.
                "group_id": None,
                "connection_url": f"ssh {username}@{floating_ip}" if username and floating_ip else None,
                "port": 22,
            })

        # App credentials (Postgres / pgAdmin templates)
        pgadmin_url = heat_outputs.get("pgadmin_url")

        for application in user_json.get("applications") or []:
            app_name = (application.get("name") or "").lower()
            is_pgadmin = "pgadmin" in app_name

            for cred in application.get("credentials") or []:
                entries.append({
                    "access_type": AccessType.DATABASE,
                    "username": cred.get("email") or cred.get("db_user") or cred.get("username"),
                    "password": cred.get("password"),
                    # course_groups.id stamped by deploy_tasks from the
                    # per-group ``course_group_id`` carried through
                    # ``generated["deployment_groups"]``. Without this,
                    # student self-service would never see app credentials
                    # (postgres/pgAdmin/...) because the filter requires a
                    # non-NULL group_id matching the student's membership.
                    "group_id": cred.get("group_id"),
                    "connection_url": pgadmin_url if is_pgadmin else None,
                    "port": 80 if is_pgadmin else None,
                })

            app_admin = application.get("admin_credentials")
            if app_admin:
                entries.append({
                    "access_type": AccessType.DATABASE,
                    "username": app_admin.get("email") or app_admin.get("db_user") or app_admin.get("username"),
                    "password": app_admin.get("password"),
                    # Admin (teacher) app credentials: group_id intentionally
                    # NULL — mirrors the SSH admin block. Lecturer-only.
                    "group_id": None,
                    "connection_url": pgadmin_url if is_pgadmin else None,
                    "port": 80 if is_pgadmin else None,
                })

        return [e for e in entries if e.get("password") or e.get("ssh_private_key")]

    def persist_activation_links(
        self,
        instance_id: str,
        overleaf_users_json: dict[str, Any],
        username_to_group_id: dict[str, str | None],
    ) -> int:
        """Append ACTIVATION_LINK access rows to an existing DeploymentInstance.

        Used for apps that generate one-time activation/setup links inside the
        playbook (no password, no SSH key) and write them to a JSON file on
        the VM that ``AnsibleService.fetch_remote_json`` then reads back.
        Currently driven by ``ansible_overleaf_latex_lab``; the input shape
        below is the contract any future app must follow to opt in.

        Expected input shape::

            {
              "admin":  {"email": str, "activation_url": str},
              "groups": [{"username": str, "email": str,
                          "activation_url": str}, ...]
            }

        ``username_to_group_id`` maps each playbook-side group ``username``
        (e.g. ``"gruppe01"``) to the corresponding ``course_groups.id``. The
        caller builds it from ``generated["deployment_groups"]``. An entry
        whose username is **not** in the map is skipped with a warning rather
        than written with ``group_id=NULL`` (that would leak the link to no
        student via the self-service filter — safer to omit it and surface
        the discrepancy in logs).

        Bypasses the ``_extract_access_entries`` password/key filter on
        purpose: that filter encodes the pre-Ansible "no password ⇒ nothing
        to store" invariant, which we don't want to weaken just for this
        post-Ansible path.

        Args:
            instance_id: ID of the already-persisted ``DeploymentInstance``
                this stack belongs to.
            overleaf_users_json: Parsed JSON read back from the VM.
            username_to_group_id: ``{playbook_username: course_groups.id}``.
                Use ``None`` as the value to deliberately produce an admin /
                lecturer-only row (currently unused — admin uses the
                separate ``admin`` block in the JSON).

        Returns:
            Number of access rows written.
        """
        instance = self.db.get(DeploymentInstance, instance_id)
        if instance is None:
            raise ValueError(
                f"persist_activation_links: DeploymentInstance {instance_id} not found"
            )

        written = 0

        # Admin entry — always group_id=None so only lecturers see it.
        admin = overleaf_users_json.get("admin") or {}
        admin_url = (admin.get("activation_url") or "").strip()
        if admin_url:
            self.db.add(
                DeploymentInstanceAccess(
                    deployment_instance_id=instance_id,
                    access_type=AccessType.ACTIVATION_LINK,
                    # Show the admin email as the "username" column in the UI
                    # — reads better than NULL.
                    username=admin.get("email"),
                    connection_url=admin_url,
                    group_id=None,
                )
            )
            written += 1

        # Per-group entries — must resolve to a known course_groups.id.
        for entry in overleaf_users_json.get("groups") or []:
            url = (entry.get("activation_url") or "").strip()
            if not url:
                continue
            username = entry.get("username")
            if not username:
                logger.warning(
                    "persist_activation_links: group entry missing 'username', skipping: %r",
                    entry,
                )
                continue
            if username not in username_to_group_id:
                logger.warning(
                    "persist_activation_links: no course_group mapping for username '%s'; "
                    "skipping rather than writing a NULL group_id row",
                    username,
                )
                continue
            gid = username_to_group_id[username]
            self.db.add(
                DeploymentInstanceAccess(
                    deployment_instance_id=instance_id,
                    access_type=AccessType.ACTIVATION_LINK,
                    username=entry.get("email") or username,
                    connection_url=url,
                    group_id=gid,
                )
            )
            written += 1

        self.db.commit()
        return written
