"""change openstack project unique constraint

Revision ID: fix_openstack_project_unique
Revises: a29c5ba5f0c2
Create Date: 2026-01-16 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'fix_openstack_project_unique'
down_revision: Union[str, Sequence[str], None] = 'a29c5ba5f0c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change unique constraint from openstack_project_id to (owner_user_id, openstack_project_id).
    
    This allows multiple users to have the same openstack_project_id, but ensures
    that each user can only have one project with a specific openstack_project_id.
    """
    # Drop the old unique constraint on openstack_project_id alone
    # PostgreSQL auto-generates constraint names like: {table}_{column}_key
    # Try the standard name first, then fallback to finding it dynamically
    try:
        op.drop_constraint('openstack_projects_openstack_project_id_key', 'openstack_projects', type_='unique')
    except Exception:
        # If standard name doesn't work, find the actual constraint name
        conn = op.get_bind()
        result = conn.execute(text("""
            SELECT constraint_name 
            FROM information_schema.table_constraints 
            WHERE table_name = 'openstack_projects' 
            AND constraint_type = 'UNIQUE'
            AND constraint_name LIKE '%openstack_project_id%'
            LIMIT 1
        """))
        row = result.fetchone()
        if row:
            op.drop_constraint(row[0], 'openstack_projects', type_='unique')
    
    # Create new composite unique constraint on (owner_user_id, openstack_project_id)
    op.create_unique_constraint(
        'uq_openstack_project_user',
        'openstack_projects',
        ['owner_user_id', 'openstack_project_id']
    )


def downgrade() -> None:
    """Revert to unique constraint on openstack_project_id only."""
    # Drop the composite unique constraint
    op.drop_constraint('uq_openstack_project_user', 'openstack_projects', type_='unique')
    
    # Restore the old unique constraint on openstack_project_id
    op.create_unique_constraint(
        'openstack_projects_openstack_project_id_key',
        'openstack_projects',
        ['openstack_project_id']
    )
