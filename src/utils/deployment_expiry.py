"""Pure-function helpers for deployment-lifetime arithmetic.

Kept free of SQLAlchemy / Pydantic so the math is unit-testable in isolation
and consumed by both the API ``DeploymentService.create_deployment`` /
``extend_deployment`` paths and the Celery-Beat sweep.

The "warning offset" — how long before ``expires_at`` the UI starts showing
the expires-soon banner — scales with the deployment's actual lifetime:

    warning_offset = min(14 days, runtime * 0.25)

so a 1-month deployment warns ~7 days before the end (not 14 — that would be
half its life), while everything from 8 weeks upward gets the flat 14-day cap.
"""
from datetime import datetime, timedelta, timezone

# Maximum vs minimum-fraction shape of the warning offset. See module docstring.
MAX_WARNING_DAYS = 14
WARNING_FRACTION_OF_RUNTIME = 0.25

# Average month length used to derive timedelta from ``runtime_months``. Calendar
# months vary; over 1..36 months this ~30.44-day approximation drifts at most a
# day or two from the calendar date — acceptable for an expiry deadline.
DAYS_PER_MONTH = 30


def _add_months(reference: datetime, months: int) -> datetime:
    """Return ``reference + months`` using the DAYS_PER_MONTH approximation.

    Anchored on ``timedelta`` rather than ``relativedelta`` so we don't pull in
    a new dependency just for this one helper.
    """
    return reference + timedelta(days=DAYS_PER_MONTH * months)


def compute_expiry(now: datetime, runtime_months: int) -> tuple[datetime, datetime]:
    """Return ``(expires_at, expiry_warning_at)`` for a freshly created deployment.

    Args:
        now: Anchor moment, typically ``datetime.now(timezone.utc)``. Pass it in
             so the API and the tests can use a fixed clock.
        runtime_months: How many months the deployment should live.

    Returns:
        Two timezone-aware UTC timestamps. Both are strictly in the future
        relative to ``now`` for any positive ``runtime_months``.
    """
    expires_at = _add_months(now, runtime_months)
    runtime = expires_at - now
    warning_offset = min(
        timedelta(days=MAX_WARNING_DAYS),
        runtime * WARNING_FRACTION_OF_RUNTIME,
    )
    return expires_at, expires_at - warning_offset


def compute_extension(
    now: datetime,
    current_expires_at: datetime | None,
    runtime_months: int,
) -> tuple[datetime, datetime]:
    """Return ``(new_expires_at, new_expiry_warning_at)`` after an extend call.

    Anchored on ``max(now, current_expires_at)``: if a deployment expired
    moments ago but the daily sweep hasn't run yet, the extension counts from
    *now* (not from the stale past); if the deployment is still valid, the
    extension stacks on top of its existing end date.

    A NULL ``current_expires_at`` (legacy / admin-pinned) is treated as ``now``
    — the extend call from the UI should give the user a fresh window to work
    with rather than throwing an error.
    """
    anchor = max(now, current_expires_at) if current_expires_at else now
    new_expires_at = _add_months(anchor, runtime_months)
    runtime = new_expires_at - now
    warning_offset = min(
        timedelta(days=MAX_WARNING_DAYS),
        runtime * WARNING_FRACTION_OF_RUNTIME,
    )
    return new_expires_at, new_expires_at - warning_offset


def utcnow() -> datetime:
    """Single source of truth for "now" in this module — easy to monkeypatch."""
    return datetime.now(timezone.utc)
