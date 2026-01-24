"""add icon_url to templates

Revision ID: add_icon_url
Revises: add_version_field
Create Date: 2026-01-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_icon_url'
down_revision: Union[str, Sequence[str], None] = 'add_version_field'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add icon_url column to templates table."""
    op.add_column('templates', 
        sa.Column('icon_url', sa.String(length=500), nullable=True,
                  comment='Icon URL or identifier (e.g., mdi:server, /icons/template.svg, 🚀)')
    )


def downgrade() -> None:
    """Remove icon_url column from templates table."""
    op.drop_column('templates', 'icon_url')
