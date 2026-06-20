"""add expiry fields to deployments

Revision ID: f7a92e3b8c41
Revises: d3f1b2c8a47e
Create Date: 2026-06-20 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a92e3b8c41'
down_revision: Union[str, Sequence[str], None] = 'd3f1b2c8a47e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds two nullable timestamps to ``deployments``:

    - ``expires_at`` — when this deployment will be hard-deleted by the
      ``expire_deployments_task`` Celery-Beat job (Heat-stack down + DB row
      removed). NULL means "never expires" (legacy rows + admin-overridden
      deployments).
    - ``expiry_warning_at`` — when the frontend should start showing the
      "läuft bald ab" banner / icon. Computed as
      ``expires_at - min(14 days, runtime * 0.25)`` so that short-runtime
      deployments do not warn for half their life.

    Both are nullable + no backfill: existing rows keep both as NULL and
    are therefore never expired by the beat job. New deployments populate
    both at creation time from ``runtime_months`` (default 4).

    Index on ``expires_at`` so the daily beat sweep
    (``WHERE expires_at < NOW() AND status NOT IN ('deleted','deleting')``)
    stays cheap as the table grows.
    """
    op.add_column(
        'deployments',
        sa.Column('expires_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'deployments',
        sa.Column('expiry_warning_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_deployments_expires_at',
        'deployments',
        ['expires_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_deployments_expires_at', table_name='deployments')
    op.drop_column('deployments', 'expiry_warning_at')
    op.drop_column('deployments', 'expires_at')
