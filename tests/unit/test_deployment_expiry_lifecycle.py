"""Tests for DeploymentService.extend_deployment and the expire_deployments
Celery-Beat sweep. Both are mocked at the repo / Celery boundary so we can
exercise the policy logic without a live DB or Heat connection.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.exceptions import BadRequestException, NotFoundException
from src.models.deployment import DeploymentStatus
from src.services.deployment_service import DeploymentService


def _utc(year=2026, month=6, day=20, hour=12):
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def _build_service(deployment):
    """DeploymentService whose deployment_repo.get_by_id returns ``deployment``.

    log_service is mocked so the audit-log call doesn't hit the DB.
    """
    db = MagicMock()
    service = DeploymentService.__new__(DeploymentService)
    service.db = db
    service.deployment_repo = MagicMock()
    service.deployment_repo.get_by_id.return_value = deployment
    service.openstack_repo = MagicMock()
    service.log_service = MagicMock()
    return service, db


# ------------------------------ extend_deployment ----------------------------

def test_extend_deployment_pushes_expires_at_forward():
    deployment = SimpleNamespace(
        id="d-1",
        status=DeploymentStatus.RUNNING,
        expires_at=_utc() + timedelta(days=30),
        expiry_warning_at=_utc() + timedelta(days=16),
    )
    service, db = _build_service(deployment)

    fixed_now = _utc()
    with patch("src.services.deployment_service.utcnow", return_value=fixed_now):
        result = service.extend_deployment("d-1", runtime_months=4)

    # Anchor was current expires_at (still in the future), plus 4 months (~120 d).
    expected_expires_at = (_utc() + timedelta(days=30)) + timedelta(days=120)
    assert result.expires_at == expected_expires_at
    # Warning recomputed.
    assert result.expiry_warning_at < result.expires_at
    db.commit.assert_called_once()
    service.log_service.log.assert_called_once()


def test_extend_deployment_anchored_on_now_when_already_expired():
    """A deployment past expires_at gets the new window from now, not the past."""
    fixed_now = _utc()
    deployment = SimpleNamespace(
        id="d-1",
        status=DeploymentStatus.RUNNING,
        expires_at=fixed_now - timedelta(days=2),  # already expired
        expiry_warning_at=fixed_now - timedelta(days=16),
    )
    service, _db = _build_service(deployment)

    with patch("src.services.deployment_service.utcnow", return_value=fixed_now):
        result = service.extend_deployment("d-1", runtime_months=4)

    expected_expires_at = fixed_now + timedelta(days=120)
    assert result.expires_at == expected_expires_at


def test_extend_deployment_handles_null_expires_at_legacy_row():
    """Legacy rows with NULL expires_at extend from now without erroring."""
    fixed_now = _utc()
    deployment = SimpleNamespace(
        id="d-1",
        status=DeploymentStatus.RUNNING,
        expires_at=None,
        expiry_warning_at=None,
    )
    service, _db = _build_service(deployment)

    with patch("src.services.deployment_service.utcnow", return_value=fixed_now):
        result = service.extend_deployment("d-1", runtime_months=4)

    assert result.expires_at == fixed_now + timedelta(days=120)
    assert result.expiry_warning_at is not None


def test_extend_deployment_404_when_missing():
    db = MagicMock()
    service = DeploymentService.__new__(DeploymentService)
    service.db = db
    service.deployment_repo = MagicMock()
    service.deployment_repo.get_by_id.return_value = None
    service.openstack_repo = MagicMock()
    service.log_service = MagicMock()

    with pytest.raises(NotFoundException):
        service.extend_deployment("nope", runtime_months=4)


def test_extend_deployment_rejects_already_deleted():
    deployment = SimpleNamespace(
        id="d-1",
        status=DeploymentStatus.DELETED,
        expires_at=None,
        expiry_warning_at=None,
    )
    service, _db = _build_service(deployment)

    with pytest.raises(BadRequestException):
        service.extend_deployment("d-1", runtime_months=4)


# ----------------------------- expire_deployments ----------------------------

class _DeploymentQueryStub:
    """Tiny stand-in for the chained SQLAlchemy ``db.query(...).filter(...).all()``.

    The real query has 3 ``.filter()`` calls in a row; whatever filter args
    arrive, we just keep returning self so the chain stays valid, then return
    the deployments fed in at construction time on ``.all()``.
    """

    def __init__(self, deployments):
        self._deployments = deployments

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._deployments


def test_expire_deployments_enqueues_delete_for_each_expired():
    """Every expired-and-non-terminal deployment should get a delete_deployment.delay."""
    expired = SimpleNamespace(
        id="d-1",
        expires_at=_utc() - timedelta(days=1),
        status=DeploymentStatus.RUNNING,
    )
    expired_2 = SimpleNamespace(
        id="d-2",
        expires_at=_utc() - timedelta(hours=2),
        status=DeploymentStatus.FAILED,
    )

    fake_db = MagicMock()
    fake_db.query.return_value = _DeploymentQueryStub([expired, expired_2])

    with patch("src.tasks.expiry_tasks.SessionLocal", return_value=fake_db), \
         patch("src.tasks.expiry_tasks.delete_deployment") as mock_delete, \
         patch("src.tasks.expiry_tasks.DeploymentLogService") as mock_log_cls, \
         patch("src.tasks.expiry_tasks.utcnow", return_value=_utc()):
        from src.tasks.expiry_tasks import expire_deployments

        # bind=True tasks expose self.request; .run() bypasses the Celery
        # binding so we can call the function body directly.
        result = expire_deployments.run()

    assert result == {"total_expired": 2, "enqueued": 2, "skipped": 0}
    assert mock_delete.delay.call_count == 2
    mock_delete.delay.assert_any_call("d-1")
    mock_delete.delay.assert_any_call("d-2")
    # Each expired deployment got an audit log entry before deletion.
    assert mock_log_cls.return_value.log.call_count == 2
    fake_db.close.assert_called_once()


def test_expire_deployments_continues_after_per_deployment_failure():
    """A bad deployment must not poison the rest of the sweep."""
    good = SimpleNamespace(
        id="good",
        expires_at=_utc() - timedelta(days=1),
        status=DeploymentStatus.RUNNING,
    )
    bad = SimpleNamespace(
        id="bad",
        expires_at=_utc() - timedelta(days=1),
        status=DeploymentStatus.RUNNING,
    )

    fake_db = MagicMock()
    fake_db.query.return_value = _DeploymentQueryStub([bad, good])

    with patch("src.tasks.expiry_tasks.SessionLocal", return_value=fake_db), \
         patch("src.tasks.expiry_tasks.delete_deployment") as mock_delete, \
         patch("src.tasks.expiry_tasks.DeploymentLogService") as mock_log_cls, \
         patch("src.tasks.expiry_tasks.utcnow", return_value=_utc()):
        # Make the FIRST log call (for "bad") raise; the second ("good") still runs.
        mock_log_cls.return_value.log.side_effect = [RuntimeError("DB down"), None]
        from src.tasks.expiry_tasks import expire_deployments

        result = expire_deployments.run()

    assert result["total_expired"] == 2
    assert result["enqueued"] == 1
    assert result["skipped"] == 1
    mock_delete.delay.assert_called_once_with("good")


def test_expire_deployments_returns_zero_when_nothing_expired():
    fake_db = MagicMock()
    fake_db.query.return_value = _DeploymentQueryStub([])

    with patch("src.tasks.expiry_tasks.SessionLocal", return_value=fake_db), \
         patch("src.tasks.expiry_tasks.delete_deployment") as mock_delete, \
         patch("src.tasks.expiry_tasks.DeploymentLogService"), \
         patch("src.tasks.expiry_tasks.utcnow", return_value=_utc()):
        from src.tasks.expiry_tasks import expire_deployments

        result = expire_deployments.run()

    assert result == {"total_expired": 0, "enqueued": 0, "skipped": 0}
    mock_delete.delay.assert_not_called()
