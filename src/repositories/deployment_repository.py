"""Repository for Deployment model."""
from typing import List, Optional
from sqlalchemy.orm import Session

from src.models.deployment import Deployment, DeploymentStatus
from src.repositories.base_repository import BaseRepository


class DeploymentRepository(BaseRepository[Deployment]):
    """Repository for Deployment CRUD operations."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentRepository."""
        super().__init__(Deployment, db)
    
    def get_by_status(self, status: DeploymentStatus, skip: int = 0, limit: int = 100) -> tuple[List[Deployment], int]:
        """Get deployments by status with pagination."""
        query = self.db.query(Deployment).filter(Deployment.status == status)
        total = query.count()
        deployments = query.offset(skip).limit(limit).all()
        return deployments, total
    
    def update_status(self, deployment_id: str, status: DeploymentStatus) -> Optional[Deployment]:
        """Update deployment status."""
        deployment = self.get_by_id(deployment_id)
        if deployment:
            deployment.status = status
            self.db.commit()
            self.db.refresh(deployment)
        return deployment
