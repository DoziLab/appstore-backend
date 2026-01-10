"""Repository for Deployment model."""
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from src.models.deployment import Deployment, DeploymentStatus
from src.repositories.base_repository import BaseRepository


class DeploymentRepository(BaseRepository[Deployment]):
    """Repository for Deployment CRUD operations."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentRepository."""
        super().__init__(Deployment, db)
    
    def get_by_course_id(self, course_id: UUID, skip: int = 0, limit: int = 100) -> tuple[List[Deployment], int]:
        """Get deployments by course ID with pagination.
        
        Args:
            course_id: Course UUID to filter by
            skip: Number of records to skip
            limit: Maximum number of records to return
            
        Returns:
            Tuple of (deployments list, total count)
        """
        query = self.db.query(Deployment).filter(Deployment.course_id == course_id)
        total = query.count()
        deployments = query.offset(skip).limit(limit).all()
        return deployments, total
    
    def get_by_status(self, status: DeploymentStatus, skip: int = 0, limit: int = 100) -> tuple[List[Deployment], int]:
        """Get deployments by status with pagination.
        
        Args:
            status: Deployment status to filter by
            skip: Number of records to skip
            limit: Maximum number of records to return
            
        Returns:
            Tuple of (deployments list, total count)
        """
        query = self.db.query(Deployment).filter(Deployment.status == status)
        total = query.count()
        deployments = query.offset(skip).limit(limit).all()
        return deployments, total
    
    def update_status(self, deployment_id: UUID, status: DeploymentStatus, error_message: Optional[str] = None) -> Optional[Deployment]:
        """Update deployment status and optional error message.
        
        Args:
            deployment_id: Deployment UUID
            status: New status
            error_message: Optional error message for failed deployments
            
        Returns:
            Updated deployment or None if not found
        """
        deployment = self.get_by_id(deployment_id)
        if deployment:
            deployment.status = status
            if error_message:
                deployment.error_message = error_message
            self.db.commit()
            self.db.refresh(deployment)
        return deployment
