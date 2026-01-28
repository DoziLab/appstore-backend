"""add_stack_create_event_type

Revision ID: 66e4c3287d2d
Revises: 60efd383df7f
Create Date: 2026-01-28 05:05:17.044033

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '66e4c3287d2d'
down_revision: Union[str, Sequence[str], None] = '60efd383df7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add STACK_CREATE to the enum type
    op.execute("ALTER TYPE deploymentlogeventtype ADD VALUE IF NOT EXISTS 'STACK_CREATE' AFTER 'TEMPLATE_CREATE'")


def downgrade() -> None:
    """Downgrade schema."""
    # Note: PostgreSQL does not support removing enum values
    # Manual intervention required if downgrade is needed
    pass
