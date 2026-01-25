"""Template Version service for business logic."""
from typing import Optional
from uuid import UUID
import logging

from sqlalchemy.orm import Session

from src.models.template_version import TemplateVersion
from src.repositories.template_version_repository import TemplateVersionRepository
from src.repositories.template_repository import TemplateRepository
from src.repositories.template_version_file_repository import TemplateVersionFileRepository
from src.schemas.template_version import TemplateVersionCreate, TemplateVersionUpdate
from src.core.exceptions import NotFoundException, BadRequestException, ForbiddenException

logger = logging.getLogger(__name__)


class TemplateVersionService:
    """Service for template version business logic."""

    def __init__(self, db: Session):
        """Initialize TemplateVersionService with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.version_repo = TemplateVersionRepository(db)
        self.template_repo = TemplateRepository(db)
        self.file_repo = TemplateVersionFileRepository(db)

    def create_version(
        self,
        version_data: TemplateVersionCreate,
        user_id: str,
        is_admin: bool = False
    ) -> TemplateVersion:
        """Create a new template version.
        
        Only template owners or admins can create versions.
        If set as active, deactivates other versions of the same template.
        
        Args:
            version_data: Version creation data
            user_id: ID of user creating the version
            is_admin: Whether the user is an admin
            
        Returns:
            Created template version
            
        Raises:
            NotFoundException: If template not found
            ForbiddenException: If user is not owner or admin
            BadRequestException: If commit SHA already exists for this template
        """
        template = self.template_repo.get_by_id(version_data.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version_data.template_id} not found")
        
        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to create versions for this template")
        
        # Check if version with same commit SHA already exists
        existing_version = self.version_repo.get_by_commit_sha(
            version_data.template_id,
            version_data.git_commit_sha
        )
        if existing_version:
            raise BadRequestException(
                f"Version with commit SHA {version_data.git_commit_sha} already exists for this template"
            )
        
        version = self.version_repo.create(
            template_id=version_data.template_id,
            version=version_data.version,
            git_commit_sha=version_data.git_commit_sha,
            is_active=version_data.is_active
        )
        
        # If this version is set as active, deactivate other versions
        if version_data.is_active:
            self.version_repo.deactivate_other_versions(
                version_data.template_id,
                version.id
            )
        
        return version

    def get_version(
        self,
        version_id: str | UUID,
        with_file_count: bool = False
    ) -> TemplateVersion | dict:
        """Get a template version by ID.
        
        Args:
            version_id: Version ID
            with_file_count: Whether to include file count
            
        Returns:
            Template version or dict with version and file_count
            
        Raises:
            NotFoundException: If version not found
        """
        if with_file_count:
            result = self.version_repo.get_with_file_count(version_id)
            if not result:
                raise NotFoundException(f"Template version with ID {version_id} not found")
            return result
        
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")
        return version

    def list_template_versions(
        self,
        template_id: str | UUID,
        active_only: bool = False
    ) -> list[TemplateVersion]:
        """List all versions for a template.
        
        Args:
            template_id: Template ID
            active_only: Whether to return only active versions
            
        Returns:
            List of template versions
            
        Raises:
            NotFoundException: If template not found
        """
        template = self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundException(f"Template with ID {template_id} not found")
        
        return self.version_repo.get_by_template_id(template_id, active_only)

    def get_active_version(
        self,
        template_id: str | UUID
    ) -> Optional[TemplateVersion]:
        """Get the active version for a template.
        
        Args:
            template_id: Template ID
            
        Returns:
            Active version or None
            
        Raises:
            NotFoundException: If template not found
        """
        template = self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundException(f"Template with ID {template_id} not found")
        
        return self.version_repo.get_active_version(template_id)

    def update_version(
        self,
        version_id: str | UUID,
        version_data: TemplateVersionUpdate,
        user_id: str,
        is_admin: bool = False
    ) -> TemplateVersion:
        """Update a template version.
        
        Only template owners or admins can update versions.
        If setting as active, deactivates other versions.
        
        Args:
            version_id: Version ID
            version_data: Version update data
            user_id: ID of user performing the update
            is_admin: Whether the user is an admin
            
        Returns:
            Updated template version
            
        Raises:
            NotFoundException: If version not found
            ForbiddenException: If user is not owner or admin
        """
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")
        
        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")
        
        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to update this template version")
        
        # Prepare update data
        update_data = version_data.model_dump(exclude_unset=True)
        
        # If setting as active, deactivate other versions first
        if update_data.get("is_active") is True:
            self.version_repo.deactivate_other_versions(
                version.template_id,
                version_id
            )
        
        uuid_id = version_id if isinstance(version_id, UUID) else UUID(str(version_id))
        updated_version = self.version_repo.update(uuid_id, **update_data)
        
        if not updated_version:
            raise NotFoundException(f"Template version with ID {version_id} not found after update")
        
        return updated_version

    def delete_version(
        self,
        version_id: str | UUID,
        user_id: str,
        is_admin: bool = False
    ) -> None:
        """Delete a template version.
        
        Only template owners or admins can delete versions.
        Cannot delete the only active version of a template.
        
        Args:
            version_id: Version ID
            user_id: ID of user performing the deletion
            is_admin: Whether the user is an admin
            
        Raises:
            NotFoundException: If version not found
            ForbiddenException: If user is not owner or admin
            BadRequestException: If trying to delete the only active version
        """
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")
        
        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")
        
        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to delete this template version")
        
        # Check if this is the only active version
        if version.is_active:
            active_versions = self.version_repo.get_by_template_id(version.template_id, active_only=True)
            if len(active_versions) == 1:
                raise BadRequestException(
                    "Cannot delete the only active version. Activate another version first or deactivate this one."
                )
        
        uuid_id = version_id if isinstance(version_id, UUID) else UUID(str(version_id))
        self.version_repo.delete(uuid_id)

    def activate_version(
        self,
        version_id: str | UUID,
        user_id: str,
        is_admin: bool = False
    ) -> TemplateVersion:
        """Activate a specific version (deactivates other versions).
        
        Args:
            version_id: Version ID to activate
            user_id: ID of user performing the action
            is_admin: Whether the user is an admin
            
        Returns:
            Activated version
            
        Raises:
            NotFoundException: If version not found
            ForbiddenException: If user is not owner or admin
        """
        version = self.version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {version_id} not found")
        
        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")
        
        if not is_admin and template.owner_id != user_id:
            raise ForbiddenException("You do not have permission to activate this template version")
        
        # Deactivate other versions
        self.version_repo.deactivate_other_versions(version.template_id, version_id)
        
        # Activate this version
        uuid_id = version_id if isinstance(version_id, UUID) else UUID(str(version_id))
        updated_version = self.version_repo.update(uuid_id, is_active=True)
        
        if not updated_version:
            raise NotFoundException(f"Template version with ID {version_id} not found after activation")
        
        return updated_version
    
    def get_version_with_parameters(
        self,
        version_id: str | UUID,
        with_file_count: bool = False
    ) -> dict:
        """Get a template version with parsed parameters from app.yaml.
        
        Args:
            version_id: Version ID
            with_file_count: Whether to include file count
            
        Returns:
            Dictionary with version data and parameters
            
        Raises:
            NotFoundException: If version not found
        """
        # Get the base version data
        if with_file_count:
            result = self.version_repo.get_with_file_count(version_id)
            if not result:
                raise NotFoundException(f"Template version with ID {version_id} not found")
            version = result["version"]
            file_count = result["file_count"]
        else:
            version = self.version_repo.get_by_id(version_id)
            if not version:
                raise NotFoundException(f"Template version with ID {version_id} not found")
            file_count = None
        
        # Load parameters using TemplateVersionFileService
        parameters = []
        
        try:
            from src.services.template_version_file_service import TemplateVersionFileService
            file_service = TemplateVersionFileService(self.db)
            params_response = file_service.get_template_parameters(str(version_id))
            # Convert TemplateParameterSchema objects to dicts for response
            parameters = [p.model_dump() for p in params_response.parameters]
            
            logger.info(
                f"Loaded {len(parameters)} parameters for version {version_id}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to load parameters for version {version_id}: {e}"
            )
        
        # Build result dictionary with only parameters
        result_dict = {
            "version": version,
            "parameters": parameters
        }
        
        if file_count is not None:
            result_dict["file_count"] = file_count
        
        return result_dict