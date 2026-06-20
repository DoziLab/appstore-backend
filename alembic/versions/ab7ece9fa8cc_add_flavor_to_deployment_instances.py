"""add flavor to deployment_instances

Revision ID: ab7ece9fa8cc
Revises: a4f2b91c30d1
Create Date: 2026-06-20 17:32:49.391619

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab7ece9fa8cc'
down_revision: Union[str, Sequence[str], None] = 'a4f2b91c30d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a nullable ``flavor`` column to ``deployment_instances`` so the
    OpenStack Nova flavor used for each instance (e.g. ``gp1.small``) is
    persisted alongside the stack metadata. The frontend resolves this
    flavor name against ``GET /api/v1/openstack/flavors`` to display real
    vCPU/RAM/disk numbers, replacing the previous hardcoded multiplier.

    Nullable + no backfill: existing rows predate this column and will
    show as ``flavor=NULL``. New deployments populate the column from
    the Heat-stack parameters at creation time.
    """
    op.add_column(
        'deployment_instances',
        sa.Column('flavor', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('deployment_instances', 'flavor')
