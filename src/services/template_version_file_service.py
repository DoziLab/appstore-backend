"""Template Version File service for business logic."""
from typing import Optional
from uuid import UUID
import yaml
import logging

from sqlalchemy.orm import Session

from src.models.template_version_file import TemplateVersionFile
from src.repositories.template_version_file_repository import TemplateVersionFileRepository
from src.schemas.template_version_file import TemplateVersionFileCreate, TemplateVersionFileUpdate
from src.schemas.template_parameters import TemplateParametersResponse, TemplateParameterSchema
from src.core.exceptions import NotFoundException, BadRequestException

logger = logging.getLogger(__name__)


class TemplateVersionFileService:
    """Service for template version file business logic."""

    def __init__(self, db: Session):
        """Initialize TemplateVersionFileService with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.file_repo = TemplateVersionFileRepository(db)

    def create_file(
        self,
        file_data: TemplateVersionFileCreate
    ) -> TemplateVersionFile:
        """Create a new template version file.
        
        Args:
            file_data: File creation data
            
        Returns:
            Created file
            
        Raises:
            BadRequestException: If trying to set multiple primary files
        """
        # Check if setting as primary and another primary file exists
        if file_data.is_primary:
            existing_primary = self.file_repo.get_primary_file(file_data.template_version_id)
            if existing_primary:
                raise BadRequestException(
                    f"Template version {file_data.template_version_id} already has a primary file: {existing_primary.file_name}"
                )
        
        file = self.file_repo.create(
            template_version_id=file_data.template_version_id,
            file_name=file_data.file_name,
            file_type=file_data.file_type,
            file_path=file_data.file_path,
            content=file_data.content,
            file_size=file_data.file_size,
            description=file_data.description,
            is_primary=file_data.is_primary,
            order=file_data.order
        )
        return file

    def get_file(
        self,
        file_id: str | UUID,
        include_content: bool = True
    ) -> TemplateVersionFile:
        """Get a file by ID.
        
        Args:
            file_id: File ID
            include_content: Whether to include file content
            
        Returns:
            File instance
            
        Raises:
            NotFoundException: If file not found
        """
        file = self.file_repo.get_by_id(file_id)
        if not file:
            raise NotFoundException(f"File with ID {file_id} not found")
        return file

    def get_version_files(
        self,
        template_version_id: str | UUID,
        include_content: bool = False,
        file_type: Optional[str] = None
    ) -> list[TemplateVersionFile]:
        """Get all files for a template version.
        
        Args:
            template_version_id: Template version ID
            include_content: Whether to include file content
            file_type: Optional filter by file type
            
        Returns:
            List of files
        """
        if file_type:
            try:
                return self.file_repo.get_by_file_type(template_version_id, file_type)
            except ValueError:
                raise BadRequestException(f"Invalid file type: {file_type}")
        
        return self.file_repo.get_by_version_id(template_version_id, include_content)

    def get_primary_file(
        self,
        template_version_id: str | UUID
    ) -> Optional[TemplateVersionFile]:
        """Get the primary deployment file for a template version.
        
        Args:
            template_version_id: Template version ID
            
        Returns:
            Primary file or None
        """
        return self.file_repo.get_primary_file(template_version_id)

    def get_file_content(
        self,
        file_id: str | UUID
    ) -> str:
        """Get the content of a specific file.
        
        Args:
            file_id: File ID
            
        Returns:
            File content
            
        Raises:
            NotFoundException: If file not found or has no content
        """
        content = self.file_repo.get_file_content(file_id)
        if content is None:
            raise NotFoundException(f"Content not found for file {file_id}")
        return content

    def update_file(
        self,
        file_id: str | UUID,
        file_data: TemplateVersionFileUpdate
    ) -> TemplateVersionFile:
        """Update a template version file.
        
        Args:
            file_id: File ID
            file_data: Update data
            
        Returns:
            Updated file
            
        Raises:
            NotFoundException: If file not found
            BadRequestException: If trying to set multiple primary files
        """
        file = self.get_file(file_id)
        
        # Check if trying to set as primary
        if file_data.is_primary and not file.is_primary:
            existing_primary = self.file_repo.get_primary_file(file.template_version_id)
            if existing_primary and str(existing_primary.id) != str(file_id):
                raise BadRequestException(
                    f"Template version already has a primary file: {existing_primary.file_name}. "
                    f"Unset it first before setting another file as primary."
                )
        
        # Update only provided fields
        update_data = file_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(file, key, value)
        
        self.db.commit()
        self.db.refresh(file)
        return file

    def update_file_content(
        self,
        file_id: str | UUID,
        content: str,
        file_size: Optional[int] = None
    ) -> TemplateVersionFile:
        """Update only the content of a file.
        
        Args:
            file_id: File ID
            content: New file content
            file_size: Optional file size in bytes
            
        Returns:
            Updated file
            
        Raises:
            NotFoundException: If file not found
        """
        file = self.file_repo.update_file_content(file_id, content, file_size)
        if not file:
            raise NotFoundException(f"File with ID {file_id} not found")
        return file

    def delete_file(
        self,
        file_id: UUID
    ) -> None:
        """Delete a template version file.
        
        Args:
            file_id: File ID
            
        Raises:
            NotFoundException: If file not found
        """
        file = self.file_repo.get_by_id(file_id)
        if not file:
            raise NotFoundException(f"File with ID {file_id} not found")
        
        self.file_repo.delete(file_id)

    def delete_version_files(
        self,
        template_version_id: str | UUID
    ) -> int:
        """Delete all files for a template version.
        
        Args:
            template_version_id: Template version ID
            
        Returns:
            Number of deleted files
        """
        return self.file_repo.delete_by_version_id(template_version_id)

    def get_deployment_files(
        self,
        template_version_id: str | UUID
    ) -> dict[str, str]:
        """Get all files needed for deployment with their content.
        
        Returns a dictionary mapping file paths to their content.
        This is used by deployment tasks.
        
        Args:
            template_version_id: Template version ID
            
        Returns:
            Dictionary of {file_path: content}
        """
        files = self.file_repo.get_by_version_id(template_version_id, include_content=True)
        
        deployment_files = {}
        for file in files:
            if file.content:
                deployment_files[file.file_path] = file.content
        
        return deployment_files

    def get_template_parameters(self, template_version_id: str) -> TemplateParametersResponse:
        """Extract Heat template parameters from template version's app.yaml file.
        
        Parses the app.yaml file for a template version and extracts parameter definitions
        that users must provide when creating deployments.
        
        Args:
            template_version_id: Template version UUID
            
        Returns:
            TemplateParametersResponse containing list of parameter definitions
            
        Raises:
            NotFoundException: If app.yaml file not found for this version
            BadRequestException: If YAML invalid or missing required sections
        """
        # Find app.yaml file for this version
        files = self.file_repo.get_by_version_id(template_version_id, include_content=True)
        app_yaml_file = next((f for f in files if f.file_name == "app.yaml"), None)
        
        if not app_yaml_file:
            raise NotFoundException(f"No app.yaml file found for template version {template_version_id}")
        
        if not app_yaml_file.content:
            raise BadRequestException("app.yaml file has no content")
        
        # Parse YAML
        try:
            yaml_data = yaml.safe_load(app_yaml_file.content)
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse app.yaml: {e}")
            raise BadRequestException(f"Invalid YAML in app.yaml: {str(e)}")
        
        if not isinstance(yaml_data, dict):
            raise BadRequestException("app.yaml must contain a YAML dictionary")
        
        # Extract parameters section
        parameters_section = yaml_data.get("parameters")
        if not parameters_section:
            raise BadRequestException("app.yaml missing 'parameters' section")
        
        if not isinstance(parameters_section, dict):
            raise BadRequestException("parameters section must be a dictionary")
        
        # Parse each parameter definition
        parameters = []
        for param_name, param_def in parameters_section.items():
            if not isinstance(param_def, dict):
                logger.warning(f"Skipping invalid parameter '{param_name}': definition must be a dict")
                continue
            
            parameters.append(
                TemplateParameterSchema(
                    name=param_name,
                    type=param_def.get("type", "string"),
                    required=param_def.get("required", False),
                    default=param_def.get("default"),
                    description=param_def.get("description", "")
                )
            )
        
        return TemplateParametersResponse(
            template_version_id=template_version_id,
            parameters=parameters
        )

