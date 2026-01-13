"""Repository for OpenStackProject model."""
from typing import Optional
from sqlalchemy.orm import Session
from src.models.openstack_project import OpenstackProject
from src.repositories.base_repository import BaseRepository


class OpenstackProjectRepository(BaseRepository[OpenstackProject]):
    """Repository for OpenStack Project CRUD operations."""
    
    def __init__(self, db: Session):
        """Initialize OpenstackProjectRepository."""
        super().__init__(OpenstackProject, db)
    
    def get_by_user_and_project_id(
        self, 
        user_id: str, 
        openstack_project_id: str
    ) -> Optional[OpenstackProject]:
        """Get OpenStack project by owner user ID and OpenStack project ID."""
        return self.db.query(OpenstackProject).filter(
            OpenstackProject.owner_user_id == user_id,
            OpenstackProject.openstack_project_id == openstack_project_id
        ).first()
    
    def get_by_owner(self, user_id: str) -> list[OpenstackProject]:
        """Get all OpenStack projects for a specific user."""
        return self.db.query(OpenstackProject).filter(
            OpenstackProject.owner_user_id == user_id
        ).all()
    
    def exists_for_user(self, user_id: str, openstack_project_id: str) -> bool:
        """Check if OpenStack project exists for user."""
        return self.db.query(OpenstackProject).filter(
            OpenstackProject.owner_user_id == user_id,
            OpenstackProject.openstack_project_id == openstack_project_id
        ).count() > 0
