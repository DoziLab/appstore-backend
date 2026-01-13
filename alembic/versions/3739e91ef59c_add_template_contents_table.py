"""add_template_contents_table

Revision ID: 3739e91ef59c
Revises: a29c5ba5f0c2
Create Date: 2026-01-13 17:17:16.676896

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3739e91ef59c'
down_revision: Union[str, Sequence[str], None] = 'a29c5ba5f0c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create template_contents table
    op.create_table(
        'template_contents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('template_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, comment='Heat template YAML content'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('template_id', 'version', name='uq_template_version')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('template_contents')
