"""Generates per-deployment credentials from the app.yaml credentials block."""
import re
import secrets
import string
from typing import Any

from src.schemas.deployment import StackAssignment, TeacherInfo


_SPECIAL = "!@#$%^&*"
_ALPHABET = string.ascii_letters + string.digits + _SPECIAL


def _generate_password(length: int = 16) -> str:
    """Generate a secure password that satisfies common complexity rules."""
    while True:
        pw = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if (
            any(c.isupper() for c in pw)
            and any(c.islower() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in _SPECIAL for c in pw)
        ):
            return pw


def _sanitize_username(name: str) -> str:
    """Convert any string to a valid Unix username (max 32 chars)."""
    username = name.lower().replace(" ", "-").replace(".", "-")
    username = re.sub(r"[^a-z0-9\-_]", "", username)
    if username and username[0].isdigit():
        username = "u" + username
    return (username or "user")[:32]


def _resolve_field(template: str, context: dict[str, Any]) -> str:
    """Replace {{ key }} placeholders with values from context."""
    def replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        # Support group_index:02d format
        if ":" in key:
            key, fmt = key.split(":", 1)
            val = context.get(key, "")
            try:
                return format(int(val), fmt)
            except (ValueError, TypeError):
                return str(val)
        return str(context.get(key, m.group(0)))

    return re.sub(r"\{\{\s*([^}]+)\s*\}\}", replacer, str(template))


def _build_credential_entry(
    spec: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build a single credential dict by resolving all field values."""
    result = {}
    for field, value in spec.items():
        if value == "generate":
            result[field] = _generate_password()
        else:
            result[field] = _resolve_field(str(value), context)
    return result


class CredentialGeneratorService:
    """Generates Ansible extra-vars from the credentials block in app.yaml.

    Replaces the old if/else template-name logic in template_user_management_service.py.
    The credentials block is read directly from app.yaml so every template controls
    exactly which credentials the backend generates.

    Usage:
        creds = CredentialGeneratorService.generate(
            credentials_spec=manifest["credentials"],
            stack_assignment=stack_assignment,
            teacher=teacher,
        )
        # creds["students"]  → list, one entry per group
        # creds["teacher"]   → dict
    """

    @staticmethod
    def generate(
        credentials_spec: dict[str, list],
        stack_assignment: StackAssignment,
        teacher: TeacherInfo,
    ) -> dict[str, Any]:
        """Generate all credentials for one stack.

        Args:
            credentials_spec: The parsed credentials block from app.yaml.
                              {"per_student": [...], "teacher": [...]}
            stack_assignment:  The stack's groups and students.
            teacher:           Teacher info from Keycloak.

        Returns:
            {
              "students": [
                {
                  "username": "gruppe01",
                  "email": "...",
                  "group_name": "Gruppe 1",
                  "group_index": 1,
                  "linux":    {"username": "gruppe01", "password": "..."},
                  "postgres": {"db_user": "grp01", "db_name": "db_g01", "password": "..."},
                  ...
                },
                ...
              ],
              "teacher": {
                "username": "prof-berg",
                "email": "...",
                "linux": {"username": "prof-berg", "password": "..."},  # always added
                "postgres": {"db_user": "teacher", "password": "..."},
                ...
              }
            }
        """
        per_student_specs: list[dict] = credentials_spec.get("per_student") or []
        teacher_specs: list[dict] = credentials_spec.get("teacher") or []

        # --- Teacher ---
        teacher_username = _sanitize_username(teacher.username)
        teacher_ctx = {
            "username": teacher_username,
            "email": teacher.email,
            "first_name": teacher.first_name,
            "last_name": teacher.last_name,
        }

        teacher_creds: dict[str, Any] = {
            "username": teacher_username,
            "email": teacher.email,
            # linux is always generated for the teacher so Ansible can connect
            "linux": {
                "username": teacher_username,
                "password": _generate_password(),
            },
        }
        for spec_item in teacher_specs:
            for cred_type, fields in spec_item.items():
                if cred_type == "linux":
                    # Merge — don't overwrite the auto-generated linux entry
                    extra = _build_credential_entry(fields, teacher_ctx)
                    teacher_creds["linux"].update(extra)
                else:
                    teacher_creds[cred_type] = _build_credential_entry(fields, teacher_ctx)

        # --- Students (one entry per group) ---
        students: list[dict[str, Any]] = []
        for group in stack_assignment.groups:
            # Use group name as the shared Linux username for the group
            group_username = _sanitize_username(group.group_name)
            # Use first student's email as group email (or generate a fallback)
            group_email = group.students[0].email if group.students else f"{group_username}@dozilab.local"

            student_ctx = {
                "username": group_username,
                "email": group_email,
                "group_name": group.group_name,
                "group_index": group.group_index,
            }

            entry: dict[str, Any] = {
                "username": group_username,
                "email": group_email,
                "group_name": group.group_name,
                "group_index": group.group_index,
                "students": [
                    {
                        "id": s.id,
                        "username": s.username,
                        "email": s.email,
                        "first_name": s.first_name,
                        "last_name": s.last_name,
                    }
                    for s in group.students
                ],
            }

            for spec_item in per_student_specs:
                for cred_type, fields in spec_item.items():
                    entry[cred_type] = _build_credential_entry(fields, student_ctx)

            students.append(entry)

        return {
            "students": students,
            "teacher": teacher_creds,
        }
