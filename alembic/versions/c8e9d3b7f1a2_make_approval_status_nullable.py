"""make template_versions.approval_status nullable

Revision ID: c8e9d3b7f1a2
Revises: b6d52b9f8ea3
Create Date: 2026-06-25 12:00:00.000000

Approval-Status ist konzeptuell nur für ``public`` Templates relevant:
deren neue Versionen brauchen einen Admin-Review, bevor sie für andere
Lecturer sichtbar werden. ``private`` Templates sind eh nur dem Owner
sichtbar — ein Approval-Flow ergibt dort keinen Sinn und steht nur als
verwirrendes ``pending``-Badge im UI rum.

Die Spalte selbst bleibt erhalten (Code-Pfade gegen ``APPROVED`` filtern
seitdem ``NULL`` semantisch wie ``not approved`` und die `WHERE = APPROVED`
SQL-Filter excludieren NULLs ohnehin korrekt). Was sich ändert:

- Spalte ist jetzt nullable
- Default bleibt ``PENDING`` (legacy callers ohne explizite Wahl)
- Neue Versionen privater Templates werden vom Service-Code explizit auf
  NULL gesetzt; öffentliche Templates verhalten sich wie bisher
- Visibility-Toggle (private↔public) durch den Code wird die Spalte
  entsprechend resetten

Keine Datenmigration: bestehende Private-Templates behalten ggf. ein
``pending``-Badge, bis die Visibility manuell getoggelt wird; das richtet
keinen Schaden an, weil der Owner sie weiterhin voll nutzen kann.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e9d3b7f1a2'
down_revision: Union[str, Sequence[str], None] = 'b6d52b9f8ea3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Postgres-Enum-Spalten brauchen den existing_type expliziet, sonst kann
    # alter_column das Enum-Detail nicht aus dem Schema rekonstruieren.
    op.alter_column(
        'template_versions',
        'approval_status',
        existing_type=sa.Enum(
            'PENDING', 'APPROVED', 'REJECTED', 'DEPRECATED',
            name='templateversionapprovalstatus',
        ),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema.

    Setzt etwaige NULL-Werte zurück auf ``PENDING`` bevor die NOT-NULL-
    Constraint wiederhergestellt wird — sonst schlägt die alter_column
    auf bestehenden NULL-Reihen fehl.
    """
    op.execute(
        "UPDATE template_versions "
        "SET approval_status = 'PENDING' "
        "WHERE approval_status IS NULL"
    )
    op.alter_column(
        'template_versions',
        'approval_status',
        existing_type=sa.Enum(
            'PENDING', 'APPROVED', 'REJECTED', 'DEPRECATED',
            name='templateversionapprovalstatus',
        ),
        nullable=False,
    )
