"""Persist deployment credentials produced by the per-stack ``user_json``."""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from src.models.deployment_instance import DeploymentInstance, DeploymentInstanceStatus
from src.models.deployment_instance_access import AccessType, DeploymentInstanceAccess


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
            # pgAdmin entries become WEB_URL accesses (the user-visible UI is
            # the pgadmin web app), everything else (postgres, mysql, ...) is
            # a DATABASE entry. The frontend renders them differently.
            access_type = AccessType.WEB_URL if is_pgadmin else AccessType.DATABASE

            for cred in application.get("credentials") or []:
                username = cred.get("email") or cred.get("db_user") or cred.get("username")
                db_name = cred.get("database_name") or cred.get("db_name")
                if is_pgadmin:
                    conn_url, port = pgadmin_url, 80
                elif username and floating_ip and db_name:
                    conn_url = f"postgresql://{username}@{floating_ip}/{db_name}"
                    port = cred.get("port") or 5432
                elif username and floating_ip:
                    conn_url = f"postgresql://{username}@{floating_ip}"
                    port = cred.get("port") or 5432
                else:
                    conn_url, port = None, cred.get("port") or 5432
                entries.append({
                    "access_type": access_type,
                    "username": username,
                    "password": cred.get("password"),
                    # Stamp the CourseGroup FK so student self-service filters
                    # work for application credentials too — without this,
                    # postgres/pgadmin entries always landed in the "Dozent" tab.
                    "group_id": cred.get("group_id"),
                    "connection_url": conn_url,
                    "port": port,
                })

            app_admin = application.get("admin_credentials")
            if app_admin:
                a_username = app_admin.get("email") or app_admin.get("db_user") or app_admin.get("username")
                entries.append({
                    "access_type": access_type,
                    "username": a_username,
                    "password": app_admin.get("password"),
                    # Admin app-credentials (e.g. pgAdmin superuser, postgres
                    # superuser) are intentionally not tied to a CourseGroup —
                    # they show up in the lecturer's "Dozent" tab.
                    "group_id": None,
                    "connection_url": pgadmin_url if is_pgadmin else (
                        f"postgresql://{a_username}@{floating_ip}" if a_username and floating_ip else None
                    ),
                    "port": 80 if is_pgadmin else 5432,
                })

        return [e for e in entries if e.get("password") or e.get("ssh_private_key")]
