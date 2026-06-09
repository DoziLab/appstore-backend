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
    ) -> DeploymentInstance:
        instance = DeploymentInstance(
            deployment_id=deployment_id,
            vm_name=stack_name,
            openstack_server_id=openstack_stack_id,
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
                    "connection_url": pgadmin_url if is_pgadmin else None,
                    "port": 80 if is_pgadmin else None,
                })

            app_admin = application.get("admin_credentials")
            if app_admin:
                entries.append({
                    "access_type": AccessType.DATABASE,
                    "username": app_admin.get("email") or app_admin.get("db_user") or app_admin.get("username"),
                    "password": app_admin.get("password"),
                    "connection_url": pgadmin_url if is_pgadmin else None,
                    "port": 80 if is_pgadmin else None,
                })

        return [e for e in entries if e.get("password")]
