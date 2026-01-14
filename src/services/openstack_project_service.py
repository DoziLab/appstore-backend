"""Service for OpenStack Project operations."""
import logging
from uuid import UUID
from sqlalchemy.orm import Session
from src.core.dependencies import RequestID
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.schemas.openstack_project import OpenstackCredentialsCreate
from src.models.openstack_project import OpenstackProject
from src.core.exceptions import NotFoundException, ForbiddenException


logger = logging.getLogger(__name__)


class OpenstackProjectService:
    """Service for managing OpenStack projects and credentials."""
    
    def __init__(self, db: Session):
        """Initialize service with database session."""
        self.db = db
        self.repository = OpenstackProjectRepository(db)
    
    def create_or_update_credentials(
        self,
        project_id: str,
        credentials: OpenstackCredentialsCreate,
        owner_user_id: str,
        request_id: RequestID,
    ) -> OpenstackProject:
        """Create or update OpenStack credentials for a project.
        
        IMPORTANT: Credentials are automatically encrypted via EncryptedString TypeDecorator.
        Never log the credentials object or its password/username fields.
        """
        # Check if project exists
        existing = self.repository.get_by_id(project_id)
        
        if existing:
            # Verify ownership
            if existing.owner_user_id != owner_user_id:
                logger.warning(
                    "Unauthorized credentials update attempt",
                    extra={
                        "request_id": request_id,
                        "project_id": project_id,
                        "owner_user_id": existing.owner_user_id,
                        "attempting_user_id": owner_user_id,
                    }
                )
                raise ForbiddenException("Not authorized to update this project's credentials")
            
            # Update existing credentials
            existing.auth_url = credentials.auth_url
            existing.username = credentials.username  # Auto-encrypted
            existing.password = credentials.password  # Auto-encrypted
            existing.user_domain_name = credentials.user_domain_name
            existing.region_name = credentials.region_name
            existing.openstack_project_id = credentials.openstack_project_id
            existing.openstack_project_name = credentials.openstack_project_name
            
            self.repository.db.commit()
            self.repository.db.refresh(existing)
            project = existing
            
            logger.info(
                "OpenStack credentials updated",
                extra={
                    "request_id": request_id,
                    "project_id": project_id,
                    "owner_user_id": owner_user_id,
                    "openstack_project_id": credentials.openstack_project_id,
                }
            )
        else:
            # Create new project with credentials
            project = self.repository.create(
                id=project_id,
                owner_user_id=owner_user_id,
                auth_url=credentials.auth_url,
                username=credentials.username,  # Auto-encrypted
                password=credentials.password,  # Auto-encrypted
                user_domain_name=credentials.user_domain_name,
                region_name=credentials.region_name,
                openstack_project_id=credentials.openstack_project_id,
                openstack_project_name=credentials.openstack_project_name,
            )
            
            logger.info(
                "OpenStack credentials created",
                extra={
                    "request_id": request_id,
                    "project_id": project_id,
                    "owner_user_id": owner_user_id,
                    "openstack_project_id": credentials.openstack_project_id,
                }
            )
        
        return project
    
    def get_credentials(
        self,
        project_id: UUID,
        user_id: str,
        request_id: RequestID,
    ) -> OpenstackProject:
        """Get OpenStack credentials for a project.
        
        Returns masked credentials via OpenstackCredentialsResponse.from_orm_masked().
        Logs access for audit trail.
        """
        project = self.repository.get_by_id(project_id)
        
        if not project:
            raise NotFoundException(f"OpenStack project {project_id} not found")
        
        # Verify ownership
        if project.owner_user_id != user_id:
            logger.warning(
                "Unauthorized credentials update attempt",
                extra={
                    "request_id": request_id,
                    "project_id": project_id,
                    "owner_user_id": project.owner_user_id,
                    "attempting_user_id": user_id,
                }
            )
            raise ForbiddenException("Not authorized to access this project's credentials")
        
        # Audit log access (never log actual credentials)
        logger.info(
            "OpenStack credentials accessed",
            extra={
                "request_id": request_id,
                "project_id": project_id,
                "user_id": user_id,
                "openstack_project_id": project.openstack_project_id,
            }
        )
        
        return project
    
    def delete_credentials(
        self,
        project_id: UUID,
        user_id: str,
        request_id: RequestID,
    ) -> None:
        """Delete OpenStack credentials for a project."""
        project = self.repository.get_by_id(project_id)
        
        if not project:
            raise NotFoundException(f"OpenStack project {project_id} not found")
        
        # Verify ownership
        if project.owner_user_id != user_id:
            logger.warning(
                "Unauthorized credentials deletion attempt",
                extra={
                    "request_id": request_id,
                    "project_id": project_id,
                    "owner_user_id": project.owner_user_id,
                    "attempting_user_id": user_id,
                }
            )
            raise ForbiddenException("Not authorized to delete this project's credentials")
        
        self.repository.delete(project_id)
        
        logger.info(
            "OpenStack credentials deleted",
            extra={
                "request_id": request_id,
                "project_id": project_id,
                "user_id": user_id,
                "openstack_project_id": project.openstack_project_id,
            }
        )
    
    def list_projects_for_user(
        self,
        user_id: str,
        request_id: RequestID,
    ) -> list[OpenstackProject]:
        """List all OpenStack projects for a user."""
        projects = self.repository.get_by_owner(user_id)
        
        logger.info(
            "OpenStack projects listed",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "count": len(projects),
            }
        )
        
        return projects
