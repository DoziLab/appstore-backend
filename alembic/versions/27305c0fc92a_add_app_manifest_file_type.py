"""add_app_manifest_file_type

Revision ID: 27305c0fc92a
Revises: fix_openstack_project_unique
Create Date: 2026-01-24 14:32:25.361098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27305c0fc92a'
down_revision: Union[str, Sequence[str], None] = 'fix_openstack_project_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add APP_MANIFEST to filetype enum."""
    # Add new enum value to existing filetype enum
    # Note: PostgreSQL doesn't support removing enum values easily in downgrade
    op.execute("ALTER TYPE filetype ADD VALUE IF NOT EXISTS 'app_manifest'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL doesn't support removing enum values directly
    # This would require recreating the entire enum and all dependent objects
    # For now, we leave the enum value in place as it's harmless
    pass
