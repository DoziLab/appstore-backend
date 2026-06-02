"""per_version_approval_and_github_app

Revision ID: a7c4f2b91d34
Revises: 66e4c3287d2d
Create Date: 2026-06-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c4f2b91d34'
down_revision: Union[str, Sequence[str], None] = '66e4c3287d2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Per-version approval, GitHub App link, and removal of template-level approval."""
    # Create dedicated enum type for version approvals
    version_approval_enum = sa.Enum(
        'pending', 'approved', 'rejected', 'deprecated',
        name='templateversionapprovalstatus',
    )
    version_approval_enum.create(op.get_bind(), checkfirst=True)

    # template_versions: approval columns
    op.add_column(
        'template_versions',
        sa.Column(
            'approval_status',
            version_approval_enum,
            nullable=False,
            server_default='pending',
        ),
    )
    op.add_column(
        'template_versions',
        sa.Column('approved_by_id', sa.String(length=36), nullable=True),
    )
    op.add_column(
        'template_versions',
        sa.Column('approved_at', sa.DateTime(), nullable=True),
    )
    op.create_foreign_key(
        'fk_template_versions_approved_by_id_users',
        source_table='template_versions',
        referent_table='users',
        local_cols=['approved_by_id'],
        remote_cols=['id'],
    )

    # Backfill: any version belonging to a previously-approved Template
    # is treated as approved so existing deployments keep working.
    op.execute(
        """
        UPDATE template_versions tv
        SET approval_status = 'approved'
        FROM templates t
        WHERE tv.template_id = t.id
          AND t.approval_status = 'APPROVED'
        """
    )

    # templates: drop the legacy template-level approval column and its enum.
    # Approval is now exclusively per-version (handled above).
    op.drop_column('templates', 'approval_status')
    sa.Enum(name='templateapprovalstatus').drop(op.get_bind(), checkfirst=True)

    # users: GitHub App installation linkage. The installation ID is a 64-bit
    # integer pointing at a specific install of our GitHub App. It is not a
    # secret (just an identifier); short-lived installation access tokens are
    # minted server-side from the App private key and never stored.
    op.add_column(
        'users',
        sa.Column('github_installation_id', sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    """Reverse the per-version approval + github-app changes."""
    op.drop_column('users', 'github_installation_id')

    # Restore templates.approval_status (best-effort: original default 'pending')
    template_approval_enum = sa.Enum(
        'PENDING', 'APPROVED', 'REJECTED', 'DEPRECATED',
        name='templateapprovalstatus',
    )
    template_approval_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'templates',
        sa.Column(
            'approval_status',
            template_approval_enum,
            nullable=False,
            server_default='PENDING',
        ),
    )

    op.drop_constraint(
        'fk_template_versions_approved_by_id_users',
        'template_versions',
        type_='foreignkey',
    )
    op.drop_column('template_versions', 'approved_at')
    op.drop_column('template_versions', 'approved_by_id')
    op.drop_column('template_versions', 'approval_status')

    sa.Enum(name='templateversionapprovalstatus').drop(op.get_bind(), checkfirst=True)
