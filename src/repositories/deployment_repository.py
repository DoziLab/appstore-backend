"""Repository for Deployment model."""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from src.models.deployment import Deployment, DeploymentStatus
from src.repositories.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class DeploymentRepository(BaseRepository[Deployment]):
    """Repository for Deployment CRUD operations."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentRepository."""
        super().__init__(Deployment, db)
    
    def get_by_status(self, status: DeploymentStatus, skip: int = 0, limit: int = 100) -> tuple[List[Deployment], int]:
        """Get deployments by status with pagination."""
        try:
            query = self.db.query(Deployment).filter(Deployment.status == status)
            total = query.count()
            deployments = query.offset(skip).limit(limit).all()
            
            logger.debug(
                "Retrieved deployments by status",
                extra={
                    "status": status.value,
                    "count": len(deployments),
                    "total": total,
                    "skip": skip,
                    "limit": limit
                }
            )
            
            return deployments, total
        except SQLAlchemyError as e:
            logger.error(
                f"Error retrieving deployments by status {status.value}: {e}",
                extra={"status": status.value},
                exc_info=True
            )
            raise
    
    def update_status(self, deployment_id: str, status: DeploymentStatus) -> Optional[Deployment]:
        """Update deployment status."""
        try:
            deployment = self.get_by_id(deployment_id)
            if deployment:
                old_status = deployment.status
                deployment.status = status
                self.db.commit()
                self.db.refresh(deployment)
                
                logger.info(
                    "Deployment status updated",
                    extra={
                        "deployment_id": deployment_id,
                        "old_status": old_status.value,
                        "new_status": status.value
                    }
                )
            else:
                logger.warning(
                    "Deployment not found for status update",
                    extra={"deployment_id": deployment_id}
                )
            
            return deployment
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.error(
                f"Error updating deployment status: {e}",
                extra={
                    "deployment_id": deployment_id,
                    "target_status": status.value
                },
                exc_info=True
            )
            raise
