"""create template_icons table

Revision ID: c8a3f1e9b7d5
Revises: e2a91d05c7b8
Create Date: 2026-07-01 09:00:00.000000

Neue Tabelle für hochgeladene Template-Icons. Bilder werden als BYTEA
persistiert, ``template_id`` ist unique (1:1 Beziehung Template → Icon)
und ``ON DELETE CASCADE`` räumt das Icon auf, wenn das Template selbst
gelöscht wird. ``icon_url`` auf ``templates`` bleibt unverändert
(externe URLs, ``mdi:*``-Identifier usw.); die Response-Aggregation im
Schema entscheidet, ob das hochgeladene Icon oder ``icon_url`` an das
Frontend gegeben wird.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c8a3f1e9b7d5'
down_revision: Union[str, Sequence[str], None] = 'e2a91d05c7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create template_icons table."""
    op.create_table(
        'template_icons',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column(
            'template_id',
            sa.String(length=36),
            nullable=False,
            comment='Owning template — 1:1, jedes Template hat höchstens ein Icon.',
        ),
        sa.Column(
            'content',
            sa.LargeBinary(),
            nullable=False,
            comment='Rohbytes des Bildes (PNG/JPEG/WebP).',
        ),
        sa.Column(
            'content_type',
            sa.String(length=64),
            nullable=False,
            comment='MIME-Typ, wird beim Ausliefern als Content-Type-Header verwendet.',
        ),
        sa.Column(
            'file_name',
            sa.String(length=255),
            nullable=True,
            comment='Original-Dateiname (für Content-Disposition).',
        ),
        sa.Column(
            'size_bytes',
            sa.Integer(),
            nullable=False,
            comment='Größe von content in Bytes.',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['template_id'],
            ['templates.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('template_id', name='uq_template_icons_template_id'),
    )


def downgrade() -> None:
    """Drop template_icons table."""
    op.drop_table('template_icons')
