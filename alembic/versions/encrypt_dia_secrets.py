"""encrypt deployment instance access secrets and add database access type

Revision ID: encrypt_dia_secrets
Revises: 66e4c3287d2d
Create Date: 2026-05-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'encrypt_dia_secrets'
down_revision: Union[str, Sequence[str], None] = '66e4c3287d2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Switch deployment_instance_access password/ssh_private_key to encrypted storage
    and extend the access_type enum with the new ``database`` member.

    The on-disk column type stays TEXT-compatible; encryption is handled by the
    EncryptedString TypeDecorator at the model layer. Because the columns have
    never been populated in production, no data backfill is needed.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Enum extension is dialect-specific. Postgres needs ALTER TYPE; SQLite stores
    # enums as plain strings via a CHECK constraint, so a no-op here is fine.
    if dialect == 'postgresql':
        op.execute("ALTER TYPE accesstype ADD VALUE IF NOT EXISTS 'database'")

    # EncryptedString writes Fernet tokens (base64); existing TEXT type already fits.
    # The alter_column calls below are intentionally minimal — they document the
    # semantic change without altering on-disk types.
    op.alter_column(
        'deployment_instance_access',
        'password',
        existing_type=sa.Text(),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'deployment_instance_access',
        'ssh_private_key',
        existing_type=sa.Text(),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Revert column annotations. Cannot remove the ``database`` enum value safely
    in PostgreSQL, so we leave it in place; downgrade is best-effort.
    """
    op.alter_column(
        'deployment_instance_access',
        'ssh_private_key',
        existing_type=sa.Text(),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'deployment_instance_access',
        'password',
        existing_type=sa.Text(),
        type_=sa.Text(),
        existing_nullable=True,
    )
