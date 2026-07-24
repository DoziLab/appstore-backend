"""cascade_delete_template_versions

Revision ID: d5e8c2a91b34
Revises: 034d40e1dad3
Create Date: 2026-06-29 12:00:00.000000

Make `template_versions.template_id` and `template_version_files.template_version_id`
cascade on delete so that deleting a template also removes its versions and the
files attached to those versions in a single transaction.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd5e8c2a91b34'
down_revision: Union[str, Sequence[str], None] = '034d40e1dad3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ON DELETE CASCADE to template_versions and template_version_files FKs."""
    # template_versions.template_id -> templates.id
    with op.batch_alter_table('template_versions') as batch_op:
        batch_op.drop_constraint('template_versions_template_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'template_versions_template_id_fkey',
            'templates',
            ['template_id'],
            ['id'],
            ondelete='CASCADE',
        )

    # template_version_files.template_version_id -> template_versions.id
    with op.batch_alter_table('template_version_files') as batch_op:
        batch_op.drop_constraint(
            'template_version_files_template_version_id_fkey', type_='foreignkey'
        )
        batch_op.create_foreign_key(
            'template_version_files_template_version_id_fkey',
            'template_versions',
            ['template_version_id'],
            ['id'],
            ondelete='CASCADE',
        )


def downgrade() -> None:
    """Revert FKs to no-cascade behavior."""
    with op.batch_alter_table('template_version_files') as batch_op:
        batch_op.drop_constraint(
            'template_version_files_template_version_id_fkey', type_='foreignkey'
        )
        batch_op.create_foreign_key(
            'template_version_files_template_version_id_fkey',
            'template_versions',
            ['template_version_id'],
            ['id'],
        )

    with op.batch_alter_table('template_versions') as batch_op:
        batch_op.drop_constraint('template_versions_template_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'template_versions_template_id_fkey',
            'templates',
            ['template_id'],
            ['id'],
        )
