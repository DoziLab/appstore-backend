"""add deployment_parameters field

Revision ID: deployment_parameters_001
Revises: a29c5ba5f0c2
Create Date: 2026-01-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'deployment_parameters_001'
down_revision: Union[str, Sequence[str], None] = 'a29c5ba5f0c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add deployment_parameters column to deployments table for Heat template parameters."""
    op.add_column(
        'deployments',
        sa.Column('deployment_parameters', sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Remove deployment_parameters column from deployments table."""
    op.drop_column('deployments', 'deployment_parameters')
