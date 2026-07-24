"""add ACTIVATION_LINK to accesstype enum

Revision ID: 034d40e1dad3
Revises: c8e9d3b7f1a2
Create Date: 2026-06-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '034d40e1dad3'
down_revision: Union[str, Sequence[str], None] = 'c8e9d3b7f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a new ``ACTIVATION_LINK`` value to the ``accesstype`` Postgres enum
    that backs ``deployment_instance_access.access_type``. Required for the
    Overleaf LaTeX Lab app (and any future app that produces one-time
    activation links during the Ansible run rather than passwords/keys
    before it): the post-Ansible SSH fetch in ``deploy_tasks`` writes such
    rows via ``DeploymentCredentialService.persist_activation_links``.

    ``IF NOT EXISTS`` keeps the migration idempotent — safe to re-run if a
    manual ALTER got there first.

    Note: ``ALTER TYPE ... ADD VALUE`` is allowed inside a transaction since
    PG 12, but the newly-added label is only usable after commit. The
    backfill of any rows using this value happens at deploy time, never in
    this migration, so the default Alembic transaction wrap is fine.
    """
    op.execute(
        "ALTER TYPE accesstype "
        "ADD VALUE IF NOT EXISTS 'ACTIVATION_LINK'"
    )


def downgrade() -> None:
    """Downgrade schema.

    Postgres does not support removing values from an enum type without
    rebuilding the type and all dependent columns. Rolling back the
    application code is the correct response; the unused enum label is
    harmless. Left intentionally empty (same approach as
    ``a1c5e8d2f307_add_expiry_enum_values_to_deployment_log``).
    """
    pass
