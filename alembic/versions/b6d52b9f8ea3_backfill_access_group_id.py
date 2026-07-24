"""backfill deployment_instance_access.group_id from existing deployments

Revision ID: b6d52b9f8ea3
Revises: b5c41a8e7d92
Create Date: 2026-06-23 17:05:00.000000

Walks every existing deployment's ``deployment_parameters`` JSON (which holds
the original ``stack_assignments[*].groups[*]`` payload), looks up the
matching ``course_groups`` row by ``(course_id, name)``, and stamps
``deployment_instance_access.group_id`` for rows whose ``username`` matches
the sanitized group name.

Idempotent: only updates rows where ``group_id IS NULL``. Re-runs are no-ops.

Skipped gracefully when:
- ``deployment_parameters`` is NULL or unparseable
- No matching ``course_groups`` row exists (lecturer never created groups via
  the courses API — those access rows stay ``group_id = NULL`` and remain
  invisible to students; lecturer-side flow is unaffected)
- The access row's ``username`` doesn't match any group's sanitized name
  (likely an admin/teacher credential — intentionally stays NULL)
"""
from __future__ import annotations

import json
import re

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6d52b9f8ea3'
down_revision: Union[str, Sequence[str], None] = 'b5c41a8e7d92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sanitize_username(name: str) -> str:
    """Mirror of credential_generator_service._sanitize_username.

    Kept inline (not imported) so the migration is self-contained and
    immune to future service-code refactors. MUST be kept byte-for-byte
    in sync with the service implementation — otherwise the backfill
    can't match existing DeploymentInstanceAccess.username rows against
    GroupMember-derived group names.
    """
    username = name.lower().replace(" ", "_").replace(".", "_").replace("-", "_")
    username = re.sub(r"[^a-z0-9_]", "", username)
    if username and username[0].isdigit():
        username = "u" + username
    return (username or "user")[:32]


def upgrade() -> None:
    """Backfill ``group_id`` on existing ``deployment_instance_access`` rows."""
    bind = op.get_bind()

    deployments = bind.execute(sa.text(
        "SELECT id, course_id, deployment_parameters "
        "FROM deployments "
        "WHERE deployment_parameters IS NOT NULL"
    )).fetchall()

    updated = 0
    for dep in deployments:
        dep_id = dep[0]
        course_id = dep[1]
        params_raw = dep[2]
        if not params_raw:
            continue
        try:
            params = json.loads(params_raw)
        except (json.JSONDecodeError, TypeError):
            continue

        stack_assignments = params.get("stack_assignments") or []
        for stack in stack_assignments:
            for group in (stack.get("groups") or []):
                group_name = group.get("group_name")
                if not group_name:
                    continue
                sanitized = _sanitize_username(group_name)

                # Find the CourseGroup row for this (course_id, group_name).
                # Older payloads may carry course_group_id directly; prefer it.
                course_group_id = group.get("course_group_id")
                if not course_group_id:
                    row = bind.execute(
                        sa.text(
                            "SELECT id FROM course_groups "
                            "WHERE course_id = :course_id AND name = :name "
                            "LIMIT 1"
                        ),
                        {"course_id": course_id, "name": group_name},
                    ).fetchone()
                    if not row:
                        # No persisted CourseGroup for this group → skip.
                        # Lecturer-side flow keeps working; students just
                        # don't see anything for this group.
                        continue
                    course_group_id = row[0]

                # Stamp any access row of this deployment whose username
                # matches the sanitized group name AND is still group_id IS NULL.
                result = bind.execute(
                    sa.text(
                        "UPDATE deployment_instance_access "
                        "SET group_id = :group_id "
                        "WHERE id IN ("
                        "  SELECT dia.id FROM deployment_instance_access dia "
                        "  JOIN deployment_instances di "
                        "    ON di.id = dia.deployment_instance_id "
                        "  WHERE di.deployment_id = :dep_id "
                        "    AND dia.username = :username "
                        "    AND dia.group_id IS NULL "
                        ")"
                    ),
                    {
                        "group_id": course_group_id,
                        "dep_id": dep_id,
                        "username": sanitized,
                    },
                )
                updated += result.rowcount or 0

    print(f"backfill complete: stamped group_id on {updated} access row(s)")


def downgrade() -> None:
    """Set all group_id back to NULL — reverses the backfill.

    Idempotent and safe: no data is destroyed; the schema column itself
    is dropped by the previous migration's downgrade.
    """
    op.execute("UPDATE deployment_instance_access SET group_id = NULL")
