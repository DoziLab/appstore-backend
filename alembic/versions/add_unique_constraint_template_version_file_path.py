"""add unique constraint on template_version_files(template_version_id, file_path)

Revision ID: b3f9c1d2e4a5
Revises: 66e4c3287d2d
Create Date: 2026-06-01

"""
from alembic import op

revision = 'b3f9c1d2e4a5'
down_revision = '66e4c3287d2d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate rows first — keep the oldest entry per (template_version_id, file_path)
    op.execute("""
        DELETE FROM template_version_files
        WHERE id NOT IN (
            SELECT DISTINCT ON (template_version_id, file_path) id
            FROM template_version_files
            ORDER BY template_version_id, file_path, created_at ASC
        )
    """)
    op.create_unique_constraint(
        'uq_template_version_file_path',
        'template_version_files',
        ['template_version_id', 'file_path']
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_template_version_file_path',
        'template_version_files',
        type_='unique'
    )
