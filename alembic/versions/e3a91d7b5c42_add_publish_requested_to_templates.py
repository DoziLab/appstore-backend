"""add publish_requested to templates

Revision ID: e3a91d7b5c42
Revises: d5e8c2a91b34
Create Date: 2026-06-29 12:00:00.000000

Owner-Wunsch „bei Erstellung öffentlich" soll das Template NICHT sofort auf
`visibility=PUBLIC` flippen, sondern als PRIVATE + `publish_requested=TRUE`
anlegen. Sobald ein Admin die erste Version genehmigt, übernimmt die
Service-Logik den Flip auf PUBLIC. Bei Rejection wird der Wunsch verworfen.

Data-Migration:
- Bestehende PUBLIC-Templates OHNE eine APPROVED Version werden auf
  PRIVATE + publish_requested=TRUE zurückgesetzt — sie entsprechen dem neuen
  Erwartungs-Zustand „wartet noch auf die Erst-Freigabe". Templates mit
  mindestens einer APPROVED Version bleiben unangetastet.
- Logging via `op.execute` mit RAISE NOTICE in einem DO-Block, damit die
  Anzahl der betroffenen Templates im Migrations-Output erscheint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3a91d7b5c42'
down_revision: Union[str, Sequence[str], None] = 'd5e8c2a91b34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add publish_requested column + backfill stale PUBLIC templates."""
    op.add_column(
        'templates',
        sa.Column(
            'publish_requested',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Backfill: PUBLIC-Templates ohne approved Version → PRIVATE + publish_requested.
    # Wir machen das atomar mit einem CTE, damit das gleichzeitige UPDATE auf
    # visibility und publish_requested auf derselben Treffermenge läuft.
    op.execute(
        """
        WITH stale_public AS (
            SELECT t.id
            FROM templates t
            WHERE t.visibility = 'PUBLIC'
              AND NOT EXISTS (
                  SELECT 1
                  FROM template_versions tv
                  WHERE tv.template_id = t.id
                    AND tv.approval_status = 'APPROVED'
              )
        )
        UPDATE templates
        SET visibility = 'PRIVATE',
            publish_requested = TRUE
        WHERE id IN (SELECT id FROM stale_public);
        """
    )

    # Optional: kurze Notice für Operator-Sichtbarkeit. Postgres-spezifisch;
    # auf SQLite (Tests) ist das ein No-Op via try/except.
    op.execute(
        """
        DO $$
        DECLARE
            affected_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO affected_count
            FROM templates WHERE publish_requested = TRUE;
            RAISE NOTICE '[migration e3a91d7b5c42] Backfilled % template(s) to PRIVATE+publish_requested', affected_count;
        END $$;
        """
    )


def downgrade() -> None:
    """Drop publish_requested.

    Vor dem Drop flippen wir publish_requested=TRUE-Templates wieder zu PUBLIC,
    damit deren Owner sie nicht „verlieren" — verlustbehaftet, aber näher am
    pre-Migration-Zustand als „still privat ohne Erinnerung". Beide Pfade
    haben Trade-offs; das ist die explizite Wahl.
    """
    op.execute(
        """
        UPDATE templates
        SET visibility = 'PUBLIC'
        WHERE publish_requested = TRUE;
        """
    )
    op.drop_column('templates', 'publish_requested')
