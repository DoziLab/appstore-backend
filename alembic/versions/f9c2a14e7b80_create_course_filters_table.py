"""create course_filters table

Revision ID: f9c2a14e7b80
Revises: ebc91d7b5d43
Create Date: 2026-06-30 12:00:00.000000

Admin-verwaltete Filter-Strings für Kursnamen (Frontend-Chips). Die Filterung
selbst läuft client-seitig — diese Tabelle hält nur die Liste der Begriffe.
``name`` ist unique, damit doppelte Chips im UI vermieden werden.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f9c2a14e7b80'
down_revision: Union[str, Sequence[str], None] = 'ebc91d7b5d43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create course_filters table."""
    op.create_table(
        'course_filters',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column(
            'name',
            sa.String(length=255),
            nullable=False,
            comment='Anzeige-/Such-String, den das Frontend gegen Kursnamen matcht',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_course_filters_name'),
    )


def downgrade() -> None:
    """Drop course_filters table."""
    op.drop_table('course_filters')
