"""add display fields to users

Revision ID: d3f1b2c8a47e
Revises: ab7ece9fa8cc
Create Date: 2026-06-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f1b2c8a47e'
down_revision: Union[str, Sequence[str], None] = 'ab7ece9fa8cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds three nullable display fields to ``users``: ``display_name``,
    ``email``, ``username``. These are CACHED copies of Keycloak token
    claims, refreshed on every login by ``UserSyncService``. They exist so
    the API can show human-readable owner names (e.g. on Template-Approval
    cards in AdminMonitoring) without round-tripping to the Keycloak Admin
    API on every request.

    Source of truth remains Keycloak — these columns are display-only and
    may be stale until the user logs in again. Roles continue to be read
    exclusively from the JWT, never from this table.

    Nullable + no backfill: existing rows predate this column. Their fields
    populate on the user's next login.
    """
    op.add_column(
        'users',
        sa.Column('display_name', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column('email', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column('username', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'username')
    op.drop_column('users', 'email')
    op.drop_column('users', 'display_name')
