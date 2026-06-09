"""Deployment Log service for business logic."""
import json
from sqlalchemy.orm import Session

from src.repositories.deployment_log_repository import DeploymentLogRepository
from src.models.deployment_log import DeploymentLog, DeploymentLogLevel, DeploymentLogEventType
from src.utils.log_sanitizer import sanitize_message, sanitize_details


class DeploymentLogService:
    """Service for deployment log business logic."""

    def __init__(self, db: Session):
        self.db = db
        self.log_repo = DeploymentLogRepository(db)

    def log(
        self,
        deployment_id: str,
        event_type: DeploymentLogEventType,
        message: str,
        level: DeploymentLogLevel = DeploymentLogLevel.INFO,
        details: dict | None = None,
        request_id: str | None = None
    ) -> DeploymentLog:
        clean_message = sanitize_message(message)
        clean_details = sanitize_details(details) if details else None
        details_json = json.dumps(clean_details) if clean_details else None

        return self.log_repo.create(
            deployment_id=deployment_id,
            level=level,
            event_type=event_type,
            message=clean_message,
            details_json=details_json,
            request_id=request_id
        )

    def get_deployment_logs(self, deployment_id: str) -> list[DeploymentLog]:
        return self.log_repo.get_by_deployment_id(deployment_id)
