"""Simplify users table - remove redundant Keycloak data.

Revision ID: slim_users_table
Revises: 54676bfeb014
Create Date: 2026-01-12 14:30:00

RATIONALE:
==========
Users table now stores ONLY what's needed for database relationships.
All user attributes (email, name, roles) are read from Keycloak token.

Changes:
- DROP email (read from token)
- DROP name (read from token)  
- DROP role (read from token - Keycloak is source of truth)
- DROP is_active (token validation handles this)
- DROP updated_at (not needed)
- RENAME created_at → keeps first login timestamp
- ADD last_login_at → track user activity

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'slim_users_table'
down_revision = '54676bfeb014'
branch_labels = None
depends_on = None


def upgrade():
    """Simplify users table to minimal foreign key reference."""
    
    # Add new column
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))
    
    # Set initial value for existing users (copy from updated_at or created_at)
    op.execute("""
        UPDATE users 
        SET last_login_at = COALESCE(updated_at, created_at)
    """)
    
    # Make last_login_at NOT NULL after data migration
    op.alter_column('users', 'last_login_at', nullable=False)
    
    # Drop redundant columns (data is in Keycloak token)
    op.drop_column('users', 'email')
    op.drop_column('users', 'name')
    op.drop_column('users', 'role')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'updated_at')
    
    # Update column comments for clarity
    op.execute("""
        COMMENT ON COLUMN users.id IS 'Local user ID for foreign keys';
        COMMENT ON COLUMN users.external_id IS 'Keycloak user UUID (sub claim) - IMMUTABLE';
        COMMENT ON COLUMN users.created_at IS 'First login timestamp';
        COMMENT ON COLUMN users.last_login_at IS 'Last successful login timestamp';
    """)


def downgrade():
    """Restore full users table structure."""
    
    # Re-add columns
    op.add_column('users', sa.Column('email', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('name', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('role', 
        postgresql.ENUM('admin', 'lecturer', 'student', name='userrole', create_type=False),
        nullable=True
    ))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(), nullable=True))
    
    # Set default values for existing users
    op.execute("""
        UPDATE users 
        SET 
            email = 'unknown@example.com',
            name = 'Unknown User',
            role = 'student',
            is_active = true,
            updated_at = last_login_at
    """)
    
    # Make columns NOT NULL after data migration
    op.alter_column('users', 'email', nullable=False)
    op.alter_column('users', 'name', nullable=False)
    op.alter_column('users', 'role', nullable=False)
    op.alter_column('users', 'updated_at', nullable=False)
    
    # Drop new column
    op.drop_column('users', 'last_login_at')
