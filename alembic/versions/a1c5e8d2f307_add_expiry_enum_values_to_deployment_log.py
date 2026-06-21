"""add expiry enum values to deployment log event type

Revision ID: a1c5e8d2f307
Revises: f7a92e3b8c41
Create Date: 2026-06-21 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1c5e8d2f307'
down_revision: Union[str, Sequence[str], None] = 'f7a92e3b8c41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    The B6 expiry work (f7a92e3b8c41) added ``expires_at`` /
    ``expiry_warning_at`` columns and the Celery-Beat sweep, but forgot to
    extend the ``deploymentlogeventtype`` PG enum with the two new audit
    events the code now emits:

    - ``DEPLOYMENT_EXPIRED`` — written by ``expire_deployments`` before each
      enqueued hard delete (see src/tasks/expiry_tasks.py).
    - ``DEPLOYMENT_LIFETIME_EXTENDED`` — written when an admin extends a
      deployment's runtime via the extend-lifetime endpoint.

    Without these labels, the first sweep on staging (2026-06-21 13:00 UTC)
    raised ``psycopg2.errors.InvalidTextRepresentation`` on the audit-log
    INSERT, which aborted the per-deployment transaction so the
    ``delete_deployment`` task was never enqueued. The sweep reported
    ``{'total_expired': 1, 'enqueued': 0, 'skipped': 1}`` and the expired
    deployment lived on.

    Both values are added with ``IF NOT EXISTS`` so this migration is safe
    to run against a database where someone (e.g. an emergency manual
    ALTER) has already added them.

    Note on Postgres semantics: ``ALTER TYPE ... ADD VALUE`` is allowed in
    a transaction since PG 12, but the newly-added value is only usable
    after the transaction commits. We do not write rows with the new value
    in this migration, so the default Alembic transaction wrap is fine.
    """
    op.execute(
        "ALTER TYPE deploymentlogeventtype "
        "ADD VALUE IF NOT EXISTS 'DEPLOYMENT_EXPIRED'"
    )
    op.execute(
        "ALTER TYPE deploymentlogeventtype "
        "ADD VALUE IF NOT EXISTS 'DEPLOYMENT_LIFETIME_EXTENDED'"
    )


def downgrade() -> None:
    """Downgrade schema.

    Postgres does not support removing values from an enum type without
    rebuilding the type and all dependent columns. Since the missing values
    were a bug (the application code already emitted them), there is no
    sensible downgrade path — rolling back the application code is the
    correct response, and the now-unused enum labels are harmless.

    Left intentionally empty.
    """
    pass
