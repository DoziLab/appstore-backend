"""Service for OpenStack Project operations."""
import logging
from typing import NoReturn
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
    
    def _update_project_credentials(
        self,
        project: OpenstackProject,
        credentials: OpenstackCredentialsCreate,
    ) -> None:
        """Update credentials for an existing project.
        
        Args:
            project: The project to update
            credentials: New credentials to apply
        """
        project.auth_url = credentials.auth_url
        project.username = credentials.username  # Auto-encrypted
        project.password = credentials.password  # Auto-encrypted
        project.user_domain_name = credentials.user_domain_name
        project.region_name = credentials.region_name
        project.openstack_project_id = credentials.openstack_project_id
        project.openstack_project_name = credentials.openstack_project_name
        
        self.repository.db.commit()
        self.repository.db.refresh(project)
    
    def _handle_integrity_error(
        self,
        e: Exception,
        project_id: str,
        owner_user_id: str,
        openstack_project_id: str,
        request_id: RequestID,
    ) -> NoReturn:
        """Handle IntegrityError and convert to ConflictException if appropriate.
        
        Args:
            e: The exception to check
            project_id: Project ID being created
            owner_user_id: Owner user ID
            openstack_project_id: OpenStack project ID
            request_id: Request ID for logging
            
        Raises:
            ConflictException: If it's a unique constraint violation
            Exception: Re-raises the original exception if not a constraint violation
        """
        from sqlalchemy.exc import IntegrityError
        from src.core.exceptions import ConflictException
        
        if isinstance(e, IntegrityError):
            error_str = str(e.orig) if hasattr(e, 'orig') else str(e)
            # Check for unique constraint violations
            if any(
                constraint in error_str
                for constraint in [
                    'uq_openstack_project_user',
                    'openstack_projects_openstack_project_id_key',
                    'duplicate key value violates unique constraint'
                ]
            ):
                logger.warning(
                    "Unique constraint violation on (owner_user_id, openstack_project_id)",
                    extra={
                        "request_id": request_id,
                        "project_id": project_id,
                        "owner_user_id": owner_user_id,
                        "openstack_project_id": openstack_project_id,
                        "error": error_str,
                    }
                )
                raise ConflictException(
                    f"An OpenStack project with ID '{openstack_project_id}' already exists for this user."
                )
        raise e
    
    def create_credentials(
        self,
        project_id: str,
        credentials: OpenstackCredentialsCreate,
        owner_user_id: str,
        request_id: RequestID,
    ) -> OpenstackProject:
        """Create a new OpenStack project with credentials.
        
        IMPORTANT: Credentials are automatically encrypted via EncryptedString TypeDecorator.
        Never log the credentials object or its password/username fields.
        
        The combination of (owner_user_id, openstack_project_id) must be unique.
        If a project with this combination already exists, raises ConflictException.
        
        Args:
            project_id: UUID of the new project
            credentials: OpenStack credentials to store
            owner_user_id: ID of the user who owns this project
            request_id: Request ID for logging
            
        Returns:
            The created OpenstackProject
            
        Raises:
            ConflictException: If a project with the same (owner_user_id, openstack_project_id) already exists
        """
        from src.core.exceptions import ConflictException
        
        # Check if project already exists for this user
        existing_by_user_and_project = self.repository.get_by_user_and_project_id(
            owner_user_id,
            credentials.openstack_project_id
        )
        
        if existing_by_user_and_project:
            logger.warning(
                "Attempt to create duplicate project for user",
                extra={
                    "request_id": request_id,
                    "project_id": project_id,
                    "owner_user_id": owner_user_id,
                    "openstack_project_id": credentials.openstack_project_id,
                    "existing_project_id": existing_by_user_and_project.id,
                }
            )
            raise ConflictException(
                f"An OpenStack project with ID '{credentials.openstack_project_id}' already exists for this user. "
                f"Use the existing project (ID: {existing_by_user_and_project.id}) or update it instead."
            )
        
        # Create new project
        try:
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
        except Exception as e:
            # _handle_integrity_error always raises an exception, never returns
            self._handle_integrity_error(
                e, project_id, owner_user_id, credentials.openstack_project_id, request_id
            )
    
    def update_credentials(
        self,
        project_id: str,
        credentials: OpenstackCredentialsCreate,
        owner_user_id: str,
        request_id: RequestID,
    ) -> OpenstackProject:
        """Update OpenStack credentials for an existing project.
        
        IMPORTANT: Credentials are automatically encrypted via EncryptedString TypeDecorator.
        Never log the credentials object or its password/username fields.
        
        Args:
            project_id: UUID of the project to update
            credentials: New OpenStack credentials
            owner_user_id: ID of the user who owns this project
            request_id: Request ID for logging
            
        Returns:
            The updated OpenstackProject
            
        Raises:
            NotFoundException: If project does not exist
            ForbiddenException: If trying to update a project owned by another user
            ConflictException: If a project with the same (owner_user_id, openstack_project_id) exists with different ID
        """
        from src.core.exceptions import ConflictException
        
        # Get project by ID
        project = self.repository.get_by_id(project_id)
        if not project:
            raise NotFoundException(f"OpenStack project {project_id} not found")
        
        # Verify ownership
        if project.owner_user_id != owner_user_id:
            logger.warning(
                "Unauthorized credentials update attempt",
                extra={
                    "request_id": request_id,
                    "project_id": project_id,
                    "owner_user_id": project.owner_user_id,
                    "attempting_user_id": owner_user_id,
                }
            )
            raise ForbiddenException("Not authorized to update this project's credentials")
        
        # Check if updating openstack_project_id would create a conflict
        if credentials.openstack_project_id != project.openstack_project_id:
            existing_by_user_and_project = self.repository.get_by_user_and_project_id(
                owner_user_id,
                credentials.openstack_project_id
            )
            if existing_by_user_and_project:
                logger.warning(
                    "Attempt to update to duplicate openstack_project_id",
                    extra={
                        "request_id": request_id,
                        "project_id": project_id,
                        "owner_user_id": owner_user_id,
                        "new_openstack_project_id": credentials.openstack_project_id,
                        "existing_project_id": existing_by_user_and_project.id,
                    }
                )
                raise ConflictException(
                    f"An OpenStack project with ID '{credentials.openstack_project_id}' already exists for this user. "
                    f"Use the existing project (ID: {existing_by_user_and_project.id}) instead."
                )
        
        # Update credentials
        # Wrap in try-except to handle race conditions where another request creates
        # a project with the same openstack_project_id between the check and commit
        try:
            self._update_project_credentials(project, credentials)
        except Exception as e:
            # Rollback the transaction on error
            self.repository.db.rollback()
            # Handle IntegrityError from unique constraint violation (race condition)
            self._handle_integrity_error(
                e, project_id, owner_user_id, credentials.openstack_project_id, request_id
            )
        
        logger.info(
            "OpenStack credentials updated",
            extra={
                "request_id": request_id,
                "project_id": str(project.id),
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
