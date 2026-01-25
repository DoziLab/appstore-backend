"""add name to deployments

Revision ID: add_name_to_deployments
Revises: add_icon_url
Create Date: 2026-01-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_name_to_deployments'
down_revision: Union[str, Sequence[str], None] = 'add_icon_url'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add name column to deployments table."""
    # Add name column with a default value for existing rows
    op.add_column('deployments', 
        sa.Column('name', sa.String(length=255), nullable=True,
                  comment='Deployment name for identification')
    )
    
    # Update existing rows with a default name based on template and course
    op.execute("""
        UPDATE deployments d
        SET name = COALESCE(
            'Deployment ' || SUBSTRING(d.id, 1, 8),
            'Deployment ' || d.id
        )
        WHERE name IS NULL
    """)
    
    # Now make it NOT NULL
    op.alter_column('deployments', 'name', nullable=False)


def downgrade() -> None:
    """Remove name column from deployments table."""
    op.drop_column('deployments', 'name')
