"""add version field to template_versions

Revision ID: add_version_field
Revises: 27305c0fc92a
Create Date: 2026-01-24 14:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_version_field'
down_revision: Union[str, Sequence[str], None] = '27305c0fc92a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add version field to template_versions table."""
    # Add version column with a default value for existing rows
    op.add_column('template_versions', 
        sa.Column('version', sa.String(length=50), nullable=True, 
                  comment='Semantic version (e.g., 0.2.0)')
    )
    
    # Update existing rows: extract version from git_commit_sha if it looks like a version
    # For now, set a default value for existing rows
    op.execute("""
        UPDATE template_versions 
        SET version = COALESCE(
            CASE 
                WHEN git_commit_sha ~ '^v?[0-9]+\.[0-9]+\.[0-9]+' 
                THEN regexp_replace(git_commit_sha, '^v?([0-9]+\.[0-9]+\.[0-9]+).*', '\\1')
                ELSE '0.1.0'
            END,
            '0.1.0'
        )
        WHERE version IS NULL
    """)
    
    # Now make it NOT NULL
    op.alter_column('template_versions', 'version', nullable=False)


def downgrade() -> None:
    """Remove version field from template_versions table."""
    op.drop_column('template_versions', 'version')
