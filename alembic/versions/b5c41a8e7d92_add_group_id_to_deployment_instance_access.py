"""add group_id to deployment_instance_access

Revision ID: b5c41a8e7d92
Revises: e7f3a91d05b8
Create Date: 2026-06-23 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5c41a8e7d92'
down_revision: Union[str, Sequence[str], None] = 'e7f3a91d05b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a nullable ``group_id`` FK on ``deployment_instance_access`` pointing
    to ``course_groups.id``. This is the missing link that lets the new
    student self-service endpoint filter credentials down to the rows the
    student is entitled to see — students see rows where ``group_id`` matches
    one of their group memberships; lecturer admin credentials use
    ``group_id IS NULL`` and remain hidden from students.

    Nullable + no default + no backfill in this migration. A separate data
    migration (``b6d52b9f8ea3_backfill...``) walks existing
    ``deployments.deployment_parameters`` JSON to retroactively populate the
    new column for pre-feature deployments.
    """
    op.add_column(
        'deployment_instance_access',
        sa.Column('group_id', sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        'fk_deployment_instance_access_group_id',
        source_table='deployment_instance_access',
        referent_table='course_groups',
        local_cols=['group_id'],
        remote_cols=['id'],
    )
    op.create_index(
        'ix_deployment_instance_access_group_id',
        'deployment_instance_access',
        ['group_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_deployment_instance_access_group_id', table_name='deployment_instance_access')
    op.drop_constraint(
        'fk_deployment_instance_access_group_id',
        'deployment_instance_access',
        type_='foreignkey',
    )
    op.drop_column('deployment_instance_access', 'group_id')
