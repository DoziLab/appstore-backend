"""Persist deployment credentials produced by the per-stack ``user_json``.

After a Heat stack is created, this service writes one ``DeploymentInstance``
row per stack and one ``DeploymentInstanceAccess`` row per credential entry
(group account, teacher admin, postgres user, pgAdmin user, ...). Passwords
are auto-encrypted by the ``EncryptedString`` type decorator on the model.
"""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from src.models.deployment_instance import DeploymentInstance, DeploymentInstanceStatus
from src.models.deployment_instance_access import AccessType, DeploymentInstanceAccess


class DeploymentCredentialService:
    """Write the credentials embedded in a stack's ``user_json`` to the database."""

    def __init__(self, db: Session):
        self.db = db

    def persist_credentials_for_stack(
        self,
        deployment_id: str,
        stack_name: str,
        openstack_stack_id: str,
        user_json: dict[str, Any],
    ) -> DeploymentInstance:
        """Persist credentials for one Heat stack.

        Creates a single ``DeploymentInstance`` for the stack and attaches one
        ``DeploymentInstanceAccess`` row per credential entry found in
        ``user_json``. Both the Ubuntu shape (credentials nested under
        ``instance``) and the Postgres shape (credentials inside
        ``applications[*]``) are supported.

        The instance status is set to ``RUNNING`` because this is called only
        after the Heat stack creation API returned successfully.
        """
        instance = DeploymentInstance(
            deployment_id=deployment_id,
            vm_name=stack_name,
            openstack_server_id=openstack_stack_id,
            status=DeploymentInstanceStatus.RUNNING,
        )
        self.db.add(instance)
        self.db.flush()  # populate instance.id for FK use below

        for entry in self._extract_access_entries(user_json):
            self.db.add(
                DeploymentInstanceAccess(
                    deployment_instance_id=instance.id,
                    access_type=entry["access_type"],
                    username=entry.get("username"),
                    password=entry.get("password"),
                )
            )

        self.db.commit()
        return instance

    @staticmethod
    def _extract_access_entries(user_json: dict[str, Any]) -> list[dict[str, Any]]:
        """Flatten a ``user_json`` payload into a list of access-row payloads.

        Returns dicts shaped like ``{access_type, username, password}``. Username
        for Postgres entries falls back to ``db_user`` since that's the field
        the postgres template uses; pgAdmin entries use ``email``.
        """
        entries: list[dict[str, Any]] = []

        instance = user_json.get("instance") or {}
        for cred in instance.get("credentials") or []:
            entries.append({
                "access_type": AccessType.SSH,
                "username": cred.get("username"),
                "password": cred.get("password"),
            })
        admin = instance.get("admin_credentials")
        if admin:
            entries.append({
                "access_type": AccessType.SSH,
                "username": admin.get("username"),
                "password": admin.get("password"),
            })

        for application in user_json.get("applications") or []:
            for cred in application.get("credentials") or []:
                entries.append({
                    "access_type": AccessType.DATABASE,
                    "username": cred.get("db_user") or cred.get("email") or cred.get("username"),
                    "password": cred.get("password"),
                })
            app_admin = application.get("admin_credentials")
            if app_admin:
                entries.append({
                    "access_type": AccessType.DATABASE,
                    "username": app_admin.get("db_user") or app_admin.get("email") or app_admin.get("username"),
                    "password": app_admin.get("password"),
                })

        return [e for e in entries if e.get("password")]
