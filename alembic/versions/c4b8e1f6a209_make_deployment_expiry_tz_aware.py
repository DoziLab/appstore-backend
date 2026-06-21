"""make deployment expiry timestamps timezone-aware

Revision ID: c4b8e1f6a209
Revises: a1c5e8d2f307
Create Date: 2026-06-21 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4b8e1f6a209'
down_revision: Union[str, Sequence[str], None] = 'a1c5e8d2f307'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    The B6 expiry work persisted ``expires_at`` and ``expiry_warning_at`` as
    ``TIMESTAMP WITHOUT TIME ZONE``. The application code, by contrast,
    always works with timezone-aware UTC datetimes (``datetime.now(timezone.utc)``).
    On round-trip through SQLAlchemy the values come back naive, which broke
    two flows in production:

    1. ``DeploymentService.extend_deployment`` calls
       ``max(now, deployment.expires_at)`` — ``TypeError`` because ``now`` is
       aware while the column value is naive.

    2. The frontend renders the JSON timestamp without a TZ suffix as local
       time, causing a 2-hour drift in MESZ on the "expires soon" banner.

    Both root-cause from the same column-type mismatch. Switching to
    ``TIMESTAMP WITH TIME ZONE`` fixes both:

    - SQLAlchemy returns aware datetimes, so the ``max()`` works.
    - The JSON serializer emits ``...+00:00``, so the frontend parses it as UTC.

    The ``USING expires_at AT TIME ZONE 'UTC'`` clause tells Postgres to
    re-interpret existing naive values as UTC moments — which is correct
    because the application has been writing ``datetime.now(timezone.utc)``
    all along; only the storage type was wrong.
    """
    op.execute(
        "ALTER TABLE deployments "
        "ALTER COLUMN expires_at TYPE TIMESTAMP WITH TIME ZONE "
        "USING expires_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE deployments "
        "ALTER COLUMN expiry_warning_at TYPE TIMESTAMP WITH TIME ZONE "
        "USING expiry_warning_at AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    """Downgrade schema.

    The reverse cast strips the timezone, leaving the underlying instant
    unchanged when viewed as UTC. Pre-rollback callers should expect to lose
    the aware-vs-naive distinction.
    """
    op.execute(
        "ALTER TABLE deployments "
        "ALTER COLUMN expiry_warning_at TYPE TIMESTAMP WITHOUT TIME ZONE "
        "USING expiry_warning_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE deployments "
        "ALTER COLUMN expires_at TYPE TIMESTAMP WITHOUT TIME ZONE "
        "USING expires_at AT TIME ZONE 'UTC'"
    )
