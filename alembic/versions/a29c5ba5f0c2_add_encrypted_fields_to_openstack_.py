"""add encrypted fields to openstack project

Revision ID: a29c5ba5f0c2
Revises: slim_users_table
Create Date: 2026-01-13 16:07:44.783131

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a29c5ba5f0c2'
down_revision: Union[str, Sequence[str], None] = 'slim_users_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - change username and password columns to TEXT for encrypted storage."""
    # Change columns to TEXT to accommodate encrypted values
    # Actual encryption/decryption is handled by the EncryptedString TypeDecorator in the model
    op.alter_column('openstack_projects', 'username',
               existing_type=sa.VARCHAR(length=255),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('openstack_projects', 'password',
               existing_type=sa.TEXT(),
               type_=sa.TEXT(),
               existing_nullable=False)
    
    # Fix users table index
    op.drop_constraint('users_external_id_key', 'users', type_='unique')
    op.create_index(op.f('ix_users_external_id'), 'users', ['external_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema - revert to original column types."""
    # Revert users table index
    op.drop_index(op.f('ix_users_external_id'), table_name='users')
    op.create_unique_constraint('users_external_id_key', 'users', ['external_id'])
    
    # Revert columns to original types
    op.alter_column('openstack_projects', 'password',
               existing_type=sa.TEXT(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('openstack_projects', 'username',
               existing_type=sa.TEXT(),
               type_=sa.VARCHAR(length=255),
               existing_nullable=False)
