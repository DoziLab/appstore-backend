"""add openstack_project_id fk to deployments

Revision ID: a4f2b91c30d1
Revises: a7c4f2b91d34
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f2b91c30d1'
down_revision: Union[str, Sequence[str], None] = 'a7c4f2b91d34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds the NOT NULL FK column ``openstack_project_id`` to ``deployments``,
    referencing ``openstack_projects.id`` (local DB primary key, NOT the
    Keystone tenant UUID).

    Assumes ``deployments`` is empty — no backfill is performed. If the table
    contains rows when this migration runs, it will fail with a NOT NULL
    constraint error. In that case, clear the table first or split this into
    (1) add column nullable=True, (2) backfill, (3) ALTER COLUMN ... SET NOT NULL.
    """
    op.add_column(
        'deployments',
        sa.Column('openstack_project_id', sa.String(length=36), nullable=False),
    )
    op.create_foreign_key(
        'fk_deployments_openstack_project_id',
        'deployments',
        'openstack_projects',
        ['openstack_project_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_deployments_openstack_project_id',
        'deployments',
        type_='foreignkey',
    )
    op.drop_column('deployments', 'openstack_project_id')
