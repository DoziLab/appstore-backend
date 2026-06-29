"""unique (template_id, version) on template_versions

Revision ID: ebc91d7b5d43
Revises: e3a91d7b5c42
Create Date: 2026-06-29 12:05:00.000000

Vor dieser Migration konnten innerhalb eines Templates beliebig viele Rows
mit identischem ``version``-String existieren — nur ``(template_id, commit_sha)``
war unique. Praxis-Effekt: jedes Repo, das `app.yaml.app.version` nicht bumpte,
landete bei „v2.0.0, v2.0.0, v2.0.0, …".

Daten-Migration:
- Schritt 1: bestehende Duplikate von ``(template_id, version)`` deduplizieren.
  Wir behalten die NEUESTE Row (höchste ``created_at``, Tie-Break per ``id``)
  unverändert und hängen an die übrigen ``+dedupe-<short_sha>`` an. Die
  Build-Metadata-Komponente (alles nach ``+``) ist laut Semver-Spec gültig
  UND sortier-neutral — der Owner sieht im UI „2.0.0+dedupe-abc12345" und
  kann das Item bei Bedarf umbenennen.
- Schritt 2: ``UniqueConstraint`` auf ``(template_id, version)`` setzen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ebc91d7b5d43'
down_revision: Union[str, Sequence[str], None] = 'e3a91d7b5c42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Dedupe + unique constraint."""
    # Schritt 1: alle Duplikate außer der jeweils neuesten umbenennen.
    # Wir nutzen eine CTE mit ROW_NUMBER, partitioniert auf (template_id, version),
    # sortiert auf created_at DESC, id DESC. rn=1 ist die zu behaltende Row,
    # rn>=2 wird umbenannt zu „<version>+dedupe-<first8(commit_sha)>".
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                template_id,
                version,
                git_commit_sha,
                ROW_NUMBER() OVER (
                    PARTITION BY template_id, version
                    ORDER BY created_at DESC, id DESC
                ) AS rn
            FROM template_versions
        )
        UPDATE template_versions tv
        SET version = ranked.version || '+dedupe-' || SUBSTRING(ranked.git_commit_sha FROM 1 FOR 8)
        FROM ranked
        WHERE tv.id = ranked.id
          AND ranked.rn > 1;
        """
    )

    # Edge-Case: nach Schritt 1 könnte das umbenannte Suffix theoretisch erneut
    # mit etwas existing kollidieren („1.0.0+dedupe-abc12345" war schon da).
    # Praktisch unwahrscheinlich (commit_sha-Prefix), aber wir loggen die
    # Gesamtzahl der renames für den Operator.
    op.execute(
        """
        DO $$
        DECLARE
            renamed_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO renamed_count
            FROM template_versions
            WHERE version LIKE '%+dedupe-%';
            RAISE NOTICE '[migration ebc91d7b5d43] Renamed % duplicate version row(s) to ''<version>+dedupe-<sha>''', renamed_count;
        END $$;
        """
    )

    # Schritt 2: jetzt darf die Constraint angelegt werden.
    op.create_unique_constraint(
        'uq_template_versions_template_id_version',
        'template_versions',
        ['template_id', 'version'],
    )


def downgrade() -> None:
    """Drop the unique constraint.

    Die ``+dedupe-…``-Suffixe werden bewusst NICHT entfernt — sie sind valider
    Semver-Build-Metadata-Anteil und liefern Rückverfolgbarkeit. Wer einen
    sauberen Rollback will, muss die Suffixe per SQL gezielt rückbauen.
    """
    op.drop_constraint(
        'uq_template_versions_template_id_version',
        'template_versions',
        type_='unique',
    )
