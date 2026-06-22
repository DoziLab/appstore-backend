"""make all timestamp columns timezone-aware

Revision ID: e7f3a91d05b8
Revises: c4b8e1f6a209
Create Date: 2026-06-22 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e7f3a91d05b8'
down_revision: Union[str, Sequence[str], None] = 'c4b8e1f6a209'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) pairs to convert. Kept as data — the upgrade/downgrade
# loops emit one ALTER COLUMN per entry. Ordered alphabetically by table for
# review readability; execution order is irrelevant because every statement
# is value-preserving and the conversion target is identical across columns.
_COLUMNS_TO_CONVERT: tuple[tuple[str, str], ...] = (
    ("courses", "created_at"),
    ("courses", "updated_at"),
    ("course_groups", "created_at"),
    ("course_groups", "updated_at"),
    ("course_members", "joined_at"),
    ("course_members", "left_at"),
    ("deployments", "created_at"),
    ("deployments", "updated_at"),
    # deployments.expires_at + expiry_warning_at already migrated in c4b8e1f6a209
    ("deployment_instances", "created_at"),
    ("deployment_instances", "updated_at"),
    ("deployment_instance_access", "expires_at"),
    ("deployment_instance_access", "created_at"),
    ("deployment_instance_access", "updated_at"),
    ("deployment_logs", "created_at"),
    ("group_members", "joined_at"),
    ("openstack_projects", "created_at"),
    ("openstack_projects", "updated_at"),
    ("templates", "created_at"),
    ("templates", "updated_at"),
    ("template_categories", "created_at"),
    ("template_categories", "updated_at"),
    ("template_category_assignments", "assigned_at"),
    ("template_versions", "approved_at"),
    ("template_versions", "created_at"),
    ("template_version_files", "created_at"),
    ("template_version_files", "updated_at"),
    ("users", "created_at"),
    ("users", "last_login_at"),
)


def upgrade() -> None:
    """Upgrade schema.

    Converts every remaining ``TIMESTAMP WITHOUT TIME ZONE`` column in the
    application schema to ``TIMESTAMP WITH TIME ZONE``. This is the
    company-wide follow-up to ``c4b8e1f6a209``, which fixed only the two
    deployment-expiry columns where the symptom was most acute (extend
    endpoint crashed; expiry banner drifted by 2 h in MESZ).

    The same root cause was already proven there: the application code has
    always written ``datetime.now(timezone.utc)`` (aware), but the storage
    type stripped the tzinfo, so values came back naive on read. Symptoms
    visible across the UI:

    - "Gestartet: 16:16" on the Deployment-Details page when the deployment
      actually started at 18:16 MESZ — Browser interprets the suffix-less
      ISO string as local time.
    - "Aktualisiert vor 2 Stunden" on the Dashboard immediately after an
      update, for the same reason.
    - AdminMonitoring tables showing log / template / user timestamps off
      by the local-time offset.

    The ``USING <col> AT TIME ZONE 'UTC'`` clause re-interprets the existing
    naive values as UTC moments. This matches what the application has
    always written, so no data movement occurs — only the storage type
    changes. Postgres rewrites the column's tuple representation (catalog
    update plus the cheapest of column rewrites since the stored values
    don't change), holding an exclusive lock for the duration of each
    ALTER. All affected tables are small in this codebase (deployments in
    the tens, users in the dozens), so the cumulative lock time is in the
    millisecond range.

    All 28 statements run in a single Alembic transaction — on failure of
    any one, the entire migration rolls back and the database state is
    exactly as before. The set was confirmed exhaustive by grepping all
    SQLAlchemy ``DateTime``-without-``timezone=True`` columns across
    ``src/models/`` before drafting this migration.
    """
    for table, column in _COLUMNS_TO_CONVERT:
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITH TIME ZONE "
            f"USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    """Downgrade schema.

    Reverses every conversion. The reverse cast strips the timezone marker
    while leaving the underlying instant unchanged when viewed as UTC.
    Callers downgrading past this migration should be aware that the
    aware-vs-naive distinction is lost on the column — which is acceptable
    in practice because the application code has always written aware
    timestamps, and reverting the application code is the correct response
    if a downgrade is ever needed.
    """
    for table, column in _COLUMNS_TO_CONVERT:
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {column} AT TIME ZONE 'UTC'"
        )
