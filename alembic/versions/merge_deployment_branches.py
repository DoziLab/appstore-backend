"""merge deployment branches

Revision ID: merge_deployment_branches
Revises: add_name_to_deployments, deployment_parameters_001
Create Date: 2026-01-24 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge_deployment_branches'
down_revision: Union[str, Sequence[str], None] = ('add_name_to_deployments', 'deployment_parameters_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the two deployment migration branches."""
    # This is a merge migration - no schema changes needed
    # Both branches have already been applied independently
    pass


def downgrade() -> None:
    """Downgrade merge migration."""
    # Merge migrations typically don't have downgrades
    pass
