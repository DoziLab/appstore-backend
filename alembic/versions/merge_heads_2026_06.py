"""merge heads: encrypt_dia_secrets and b3f9c1d2e4a5

Revision ID: merge_heads_2026_06
Revises: encrypt_dia_secrets, b3f9c1d2e4a5
Create Date: 2026-06-09

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'merge_heads_2026_06'
down_revision: Union[str, Sequence[str], None] = ('encrypt_dia_secrets', 'b3f9c1d2e4a5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
