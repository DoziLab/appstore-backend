"""create template_icons table + drop templates.icon_url

Revision ID: c8a3f1e9b7d5
Revises: e2a91d05c7b8
Create Date: 2026-07-01 09:00:00.000000

Zwei Änderungen in einer Migration, weil sie inhaltlich zusammengehören
und dieser Feature-Branch noch nicht deployt ist (kein Bestand zu retten):

1. Neue Tabelle ``template_icons`` — hält hochgeladene Icon-Bilder als
   BYTEA. ``template_id`` unique (1:1) und ``ON DELETE CASCADE``, damit
   die Row automatisch mitgeht, wenn das Template gelöscht wird.

2. Alte Spalte ``templates.icon_url`` fliegt raus. Icons kommen ab jetzt
   ausschließlich als Upload; ``mdi:*``-Strings/URLs werden nicht mehr
   unterstützt. Frontend zeigt für Templates ohne hochgeladenes Bild
   einen Placeholder.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c8a3f1e9b7d5'
down_revision: Union[str, Sequence[str], None] = 'e2a91d05c7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create template_icons table and drop templates.icon_url."""
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

    # icon_url wird durch hochgeladene Icons ersetzt. Kein Bestand zu retten
    # (dieser Branch ist noch nicht deployed), also einfach droppen.
    op.drop_column('templates', 'icon_url')


def downgrade() -> None:
    """Restore templates.icon_url and drop template_icons."""
    op.add_column(
        'templates',
        sa.Column(
            'icon_url',
            sa.String(length=500),
            nullable=True,
            comment='Icon URL or identifier (e.g., mdi:server, /icons/template.svg, 🚀)',
        ),
    )
    op.drop_table('template_icons')
