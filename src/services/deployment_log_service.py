"""Deployment Log service for business logic."""
import json
from sqlalchemy.orm import Session

from src.repositories.deployment_log_repository import DeploymentLogRepository
from src.models.deployment_log import DeploymentLog, DeploymentLogLevel, DeploymentLogEventType


class DeploymentLogService:
    """Service for deployment log business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentLogService with database session."""
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
        """Create a deployment log entry.
        
        Args:
            deployment_id: ID of the deployment
            event_type: Type of event
            message: Log message
            level: Log level (default: INFO)
            details: Additional details as dictionary
            request_id: Request correlation ID
            
        Returns:
            Created DeploymentLog instance
        """
        details_json = json.dumps(details) if details else None
        
        return self.log_repo.create(
            deployment_id=deployment_id,
            level=level,
            event_type=event_type,
            message=message,
            details_json=details_json,
            request_id=request_id
        )
    
    def get_deployment_logs(self, deployment_id: str) -> list[DeploymentLog]:
        """Get all logs for a deployment.
        
        Args:
            deployment_id: ID of the deployment
            
        Returns:
            List of deployment logs ordered by time
        """
        return self.log_repo.get_by_deployment_id(deployment_id)
