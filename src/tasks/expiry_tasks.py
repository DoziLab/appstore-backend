"""Celery-Beat task that hard-deletes expired deployments.

Scheduled in ``src/celery_app.py`` to run once per day. The task fetches
all deployments whose ``expires_at`` lies in the past and that are not
already terminal (DELETED) or mid-deletion (DELETING), then enqueues
``delete_deployment`` for each one — same Heat-stack-down + DB-row-removal
path used by the user-initiated DELETE endpoint, so there is no second
deletion code path to maintain.

Logs a ``DEPLOYMENT_EXPIRED`` audit entry per deployment before enqueuing
the deletion so the lifecycle decision is auditable independently of the
deletion's own logging. Idempotent: a deployment whose ``delete_deployment``
task is still running gets caught on the next sweep by its DELETING status
and skipped.
"""
from __future__ import annotations

import logging

from src.celery_app import celery_app
from src.core.database import SessionLocal
from src.models.deployment import Deployment, DeploymentStatus
from src.models.deployment_log import DeploymentLogEventType, DeploymentLogLevel
from src.services.deployment_log_service import DeploymentLogService
from src.tasks.deploy_tasks import delete_deployment
from src.utils.deployment_expiry import utcnow

logger = logging.getLogger(__name__)

# Statuses that block expiry from running. DELETED is already terminal,
# DELETING means a deletion is in flight — second sweep would race the first.
_TERMINAL_OR_TRANSITIONAL = (
    DeploymentStatus.DELETED,
    DeploymentStatus.DELETING,
)


@celery_app.task(bind=True, name="src.tasks.expiry_tasks.expire_deployments")
def expire_deployments(self) -> dict:
    """Find deployments past ``expires_at`` and enqueue their deletion.

    Returns:
        Summary dict ``{"total_expired": n, "enqueued": m, "skipped": k}``
        for log/monitoring purposes.
    """
    task_id = self.request.id
    now = utcnow()
    logger.info(
        "expire_deployments sweep starting",
        extra={"task_id": task_id, "now": now.isoformat()},
    )

    db = SessionLocal()
    enqueued = 0
    skipped = 0
    candidates: list[Deployment] = []
    try:
        # SQL pre-filter on the indexed expires_at column; status filter is
        # cheap once the candidate set is small.
        candidates = (
            db.query(Deployment)
            .filter(Deployment.expires_at.is_not(None))
            .filter(Deployment.expires_at < now)
            .filter(Deployment.status.notin_(_TERMINAL_OR_TRANSITIONAL))
            .all()
        )

        log_service = DeploymentLogService(db)

        for deployment in candidates:
            deployment_id = str(deployment.id)
            try:
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_EXPIRED,
                    message=(
                        f"Deployment expired at {deployment.expires_at.isoformat()}; "
                        f"enqueuing hard delete"
                    ),
                    level=DeploymentLogLevel.INFO,
                    details={
                        "expires_at": deployment.expires_at.isoformat(),
                        "swept_at": now.isoformat(),
                        "previous_status": deployment.status.value,
                    },
                )
                # Hand off to the existing deletion pipeline — same path as the
                # user-initiated DELETE endpoint.
                delete_deployment.delay(deployment_id)
                enqueued += 1
            except Exception as e:
                # One bad deployment must not poison the whole sweep.
                logger.error(
                    "Failed to enqueue expiry deletion for deployment",
                    extra={
                        "deployment_id": deployment_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                skipped += 1

    finally:
        db.close()

    summary = {
        "total_expired": len(candidates),
        "enqueued": enqueued,
        "skipped": skipped,
    }
    logger.info(
        "expire_deployments sweep complete",
        extra={"task_id": task_id, **summary},
    )
    return summary
