"""add REDEPLOYING to deploymentinstancestatus enum

Revision ID: e2a91d05c7b8
Revises: f9c2a14e7b80
Create Date: 2026-06-30 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2a91d05c7b8'
down_revision: Union[str, Sequence[str], None] = 'f9c2a14e7b80'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a new ``REDEPLOYING`` value to the ``deploymentinstancestatus``
    Postgres enum so the ``redeploy_instance`` Celery task can mark a single
    DeploymentInstance row as transient while it tears down + recreates its
    Heat stack, without flipping the parent Deployment to RESTARTING (which
    would block the user from running other ops on its siblings).

    ``IF NOT EXISTS`` keeps the migration idempotent — safe to re-run if a
    manual ALTER got there first. Same approach as
    ``034d40e1dad3_add_activation_link_to_access_type``.
    """
    op.execute(
        "ALTER TYPE deploymentinstancestatus "
        "ADD VALUE IF NOT EXISTS 'REDEPLOYING'"
    )


def downgrade() -> None:
    """Downgrade schema.

    Postgres does not support removing values from an enum type without
    rebuilding the type and all dependent columns. Rolling back the
    application code is the correct response; the unused enum label is
    harmless. Left intentionally empty (mirrors
    ``034d40e1dad3_add_activation_link_to_access_type``).
    """
    pass
