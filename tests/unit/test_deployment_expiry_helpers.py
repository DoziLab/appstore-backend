"""Tests for the deployment-expiry pure-function helpers.

Pure math, no DB, no network — covers the warning-offset rule and the
``max(now, current_expires_at)`` anchor on extension.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.utils.deployment_expiry import (
    DAYS_PER_MONTH,
    MAX_WARNING_DAYS,
    WARNING_FRACTION_OF_RUNTIME,
    compute_expiry,
    compute_extension,
)


def _now() -> datetime:
    return datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("months", [1, 3, 4, 6, 12, 24, 36])
def test_compute_expiry_returns_two_future_timestamps(months: int):
    """expires_at and expiry_warning_at must both be in the future."""
    now = _now()
    expires_at, warning_at = compute_expiry(now, months)

    assert expires_at > now
    assert warning_at > now
    # Warning must always come before the actual expiry.
    assert warning_at < expires_at


def test_compute_expiry_4_months_caps_warning_at_14_days():
    """For the default 4-month lifetime, warning kicks in 14 days before end."""
    now = _now()
    expires_at, warning_at = compute_expiry(now, 4)

    assert (expires_at - now).days == DAYS_PER_MONTH * 4
    assert (expires_at - warning_at) == timedelta(days=MAX_WARNING_DAYS)


def test_compute_expiry_12_months_still_caps_at_14_days():
    """Long lifetimes hit the 14-day cap, not the 25%-of-runtime fraction."""
    now = _now()
    expires_at, warning_at = compute_expiry(now, 12)
    assert (expires_at - warning_at) == timedelta(days=MAX_WARNING_DAYS)


def test_compute_expiry_1_month_uses_runtime_fraction_not_cap():
    """A 1-month deployment must NOT warn for half its life — 14d cap is too long.

    Expected offset = 30 days * 0.25 = 7.5 days, not the 14-day cap.
    """
    now = _now()
    expires_at, warning_at = compute_expiry(now, 1)

    expected_offset = timedelta(days=DAYS_PER_MONTH) * WARNING_FRACTION_OF_RUNTIME
    actual_offset = expires_at - warning_at
    assert actual_offset == expected_offset
    # Sanity check: this is well under the 14d cap.
    assert actual_offset < timedelta(days=MAX_WARNING_DAYS)


def test_compute_extension_stacks_on_existing_expires_at_when_still_valid():
    """An extend on a still-valid deployment counts from its existing end date."""
    now = _now()
    current_expires_at = now + timedelta(days=30)  # 30 days left

    new_expires_at, _ = compute_extension(now, current_expires_at, runtime_months=4)

    expected = current_expires_at + timedelta(days=DAYS_PER_MONTH * 4)
    assert new_expires_at == expected


def test_compute_extension_anchors_on_now_when_already_expired():
    """If current_expires_at lies in the past, extend from now — not from the past."""
    now = _now()
    current_expires_at = now - timedelta(days=2)  # already expired

    new_expires_at, _ = compute_extension(now, current_expires_at, runtime_months=4)

    expected = now + timedelta(days=DAYS_PER_MONTH * 4)
    assert new_expires_at == expected


def test_compute_extension_handles_null_current_expires_at():
    """Legacy/admin-pinned deployments with NULL expires_at extend from now."""
    now = _now()

    new_expires_at, _ = compute_extension(now, None, runtime_months=4)

    expected = now + timedelta(days=DAYS_PER_MONTH * 4)
    assert new_expires_at == expected


def test_compute_extension_recomputes_warning_offset_from_new_runtime():
    """expiry_warning_at after extend must follow the same rule as creation."""
    now = _now()
    current_expires_at = now + timedelta(days=30)

    new_expires_at, new_warning_at = compute_extension(
        now, current_expires_at, runtime_months=4
    )
    runtime = new_expires_at - now
    expected_offset = min(
        timedelta(days=MAX_WARNING_DAYS),
        runtime * WARNING_FRACTION_OF_RUNTIME,
    )
    assert (new_expires_at - new_warning_at) == expected_offset
