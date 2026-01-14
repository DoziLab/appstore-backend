"""Deployment Log repository for database operations."""
from sqlalchemy.orm import Session

from src.models.deployment_log import DeploymentLog
from src.repositories.base_repository import BaseRepository


class DeploymentLogRepository(BaseRepository[DeploymentLog]):
    """Repository for DeploymentLog database operations."""

    def __init__(self, db: Session):
        """Initialize DeploymentLogRepository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        super().__init__(DeploymentLog, db)
    
    def get_by_deployment_id(self, deployment_id: str) -> list[DeploymentLog]:
        """Get all logs for a specific deployment ordered by creation time.
        
        Args:
            deployment_id: ID of the deployment
            
        Returns:
            List of deployment logs ordered by created_at ascending
        """
        return (
            self.db.query(self.model)
            .filter(self.model.deployment_id == deployment_id)
            .order_by(self.model.created_at.asc())
            .all()
        )
