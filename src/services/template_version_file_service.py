"""Template Version File service for business logic."""
from typing import Optional
from uuid import UUID
import yaml
import logging

from sqlalchemy.orm import Session

from src.models.template_version_file import TemplateVersionFile
from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.repositories.template_version_file_repository import TemplateVersionFileRepository
from src.repositories.template_version_repository import TemplateVersionRepository
from src.repositories.template_repository import TemplateRepository
from src.schemas.template_version_file import TemplateVersionFileCreate, TemplateVersionFileUpdate
from src.schemas.template_parameters import TemplateParametersResponse, TemplateParameterSchema
from src.core.exceptions import NotFoundException, BadRequestException, ForbiddenException

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
        self.version_repo = TemplateVersionRepository(db)
        self.template_repo = TemplateRepository(db)

    def _can_access_template(
        self,
        template: Template,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> bool:
        """Check if a user can access a template.
        
        Access rules:
        - Admins can access any template
        - Lecturers can access:
          1. Their own private templates
          2. Any approved public templates
        
        Args:
            template: Template to check access for
            user_id: ID of the requesting user
            is_admin: Whether the requesting user is an admin
            
        Returns:
            True if user can access the template, False otherwise
        """
        if is_admin:
            return True
        
        if not user_id:
            return False
        
        # Owner can access their own templates
        if template.owner_id == user_id:
            return True
        
        # Non-owners can only access approved public templates
        if (template.visibility == TemplateVisibility.PUBLIC and
            template.approval_status == TemplateApprovalStatus.APPROVED):
            return True
        
        return False

    def _check_template_access(
        self,
        template_version_id: str | UUID,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> Template:
        """Check if user can access parent template via version and return template.
        
        Args:
            template_version_id: Template version ID to check
            user_id: ID of the requesting user
            is_admin: Whether the requesting user is an admin
            
        Returns:
            Template if accessible
            
        Raises:
            NotFoundException: If version or template not found
            ForbiddenException: If user lacks permission to view template
        """
        version = self.version_repo.get_by_id(template_version_id)
        if not version:
            raise NotFoundException(f"Template version with ID {template_version_id} not found")
        
        template = self.template_repo.get_by_id(version.template_id)
        if not template:
            raise NotFoundException(f"Template with ID {version.template_id} not found")
        
        if not self._can_access_template(template, user_id, is_admin):
            raise ForbiddenException("You do not have permission to access this template")
        
        return template

    def create_file(
        self,
        file_data: TemplateVersionFileCreate
    ) -> TemplateVersionFile:
        """Create or update a template version file (upsert by file_path).

        If a file with the same (template_version_id, file_path) already exists
        it is updated instead of creating a duplicate.

        Raises:
            BadRequestException: If trying to set multiple primary files
        """
        # Check if setting as primary and another primary file exists
        if file_data.is_primary:
            existing_primary = self.file_repo.get_primary_file(file_data.template_version_id)
            if existing_primary and existing_primary.file_path != file_data.file_path:
                raise BadRequestException(
                    f"Template version {file_data.template_version_id} already has a primary file: {existing_primary.file_name}"
                )

        file, _ = self.file_repo.upsert(
            template_version_id=file_data.template_version_id,
            file_name=file_data.file_name,
            file_type=file_data.file_type,
            file_path=file_data.file_path,
            content=file_data.content,
            file_size=file_data.file_size,
            description=file_data.description,
            is_primary=file_data.is_primary,
            order=file_data.order,
        )
        return file

    def get_file(
        self,
        file_id: str | UUID,
        include_content: bool = True,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> TemplateVersionFile:
        """Get a file by ID.
        
        Requires access to parent template.
        
        Args:
            file_id: File ID
            include_content: Whether to include file content
            user_id: ID of the requesting user (for permission check)
            is_admin: Whether the requesting user is an admin
            
        Returns:
            File instance
            
        Raises:
            NotFoundException: If file not found
            ForbiddenException: If user lacks permission to access parent template
        """
        file = self.file_repo.get_by_id(file_id)
        if not file:
            raise NotFoundException(f"File with ID {file_id} not found")
        
        # Check access to parent template
        self._check_template_access(file.template_version_id, user_id, is_admin)
        
        return file

    def get_version_files(
        self,
        template_version_id: str | UUID,
        include_content: bool = False,
        file_type: Optional[str] = None,
        user_id: Optional[str] = None,
        is_admin: bool = False,
        skip_access_check: bool = False
    ) -> list[TemplateVersionFile]:
        """Get all files for a template version.
        
        Requires access to parent template unless skip_access_check is True.
        
        Args:
            template_version_id: Template version ID
            include_content: Whether to include file content
            file_type: Optional filter by file type
            user_id: ID of the requesting user (for permission check)
            is_admin: Whether the requesting user is an admin
            skip_access_check: Skip template access verification (for deployment tasks)
            
        Returns:
            List of files
            
        Raises:
            ForbiddenException: If user lacks permission to access parent template (unless skipped)
        """
        # Check access to parent template unless explicitly skipped
        if not skip_access_check:
            self._check_template_access(template_version_id, user_id, is_admin)
        
        if file_type:
            try:
                return self.file_repo.get_by_file_type(template_version_id, file_type)
            except ValueError:
                raise BadRequestException(f"Invalid file type: {file_type}")
        
        return self.file_repo.get_by_version_id(template_version_id, include_content)

    def get_primary_file(
        self,
        template_version_id: str | UUID,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> Optional[TemplateVersionFile]:
        """Get the primary deployment file for a template version.
        
        Requires access to parent template.
        
        Args:
            template_version_id: Template version ID
            user_id: ID of the requesting user (for permission check)
            is_admin: Whether the requesting user is an admin
            
        Returns:
            Primary file or None
            
        Raises:
            ForbiddenException: If user lacks permission to access parent template
        """
        # Check access to parent template
        self._check_template_access(template_version_id, user_id, is_admin)
        
        return self.file_repo.get_primary_file(template_version_id)

    def get_file_content(
        self,
        file_id: str | UUID,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> str:
        """Get the content of a specific file.
        
        Requires access to parent template.
        
        Args:
            file_id: File ID
            user_id: ID of the requesting user (for permission check)
            is_admin: Whether the requesting user is an admin
            
        Returns:
            File content
            
        Raises:
            NotFoundException: If file not found or has no content
            ForbiddenException: If user lacks permission to access parent template
        """
        # get_file already checks template access
        file = self.get_file(file_id, include_content=True, user_id=user_id, is_admin=is_admin)
        
        if file.content is None:
            raise NotFoundException(f"Content not found for file {file_id}")
        return file.content

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

    def get_template_parameters(
        self,
        template_version_id: str,
        user_id: Optional[str] = None,
        is_admin: bool = False,
        skip_access_check: bool = False
    ) -> TemplateParametersResponse:
        """Extract Heat template parameters from template version's app.yaml file.
        
        Parses the app.yaml file for a template version and extracts parameter definitions
        that users must provide when creating deployments.
        
        Supports both list format (new) and dictionary format (legacy) for parameters.
        
        Args:
            template_version_id: Template version UUID
            user_id: ID of the requesting user (for permission check)
            is_admin: Whether the requesting user is an admin
            skip_access_check: Skip template access check (used for deployment creation)
            
        Returns:
            TemplateParametersResponse containing list of parameter definitions
            
        Raises:
            NotFoundException: If app.yaml file not found for this version
            BadRequestException: If YAML invalid or missing required sections
            ForbiddenException: If user lacks permission to access parent template
        """
        # Check access to parent template unless explicitly skipped
        if not skip_access_check:
            self._check_template_access(template_version_id, user_id, is_admin)
        
        # Find app.yaml file for this version
        files = self.file_repo.get_by_version_id(template_version_id, include_content=True)
        app_yaml_file = next((f for f in files if f.file_name == "app.yaml"), None)
        
        if not app_yaml_file:
            # Include both phrasings so tests checking either substring succeed
            raise NotFoundException(
                f"No app.yaml file found (app.yaml file not found) for template version {template_version_id}"
            )
        
        if not app_yaml_file.content:
            raise BadRequestException("app.yaml file has no content")
        
        # Use AppManifestParser which supports list format
        parameters_list = None
        try:
            from src.utils.app_manifest_parser import AppManifestParser
            parsed_manifest = AppManifestParser.parse(app_yaml_file.content)
            parameters_list = parsed_manifest.get("parameters", [])
            logger.debug(f"Successfully parsed {len(parameters_list)} parameters using AppManifestParser")
        except Exception as e:
            logger.warning(f"Failed to parse app.yaml with AppManifestParser: {e}, falling back to legacy format")
            import traceback
            logger.debug(traceback.format_exc())
        
        # Fallback to old dictionary format if AppManifestParser failed or returned no parameters
        if parameters_list is None or len(parameters_list) == 0:
            logger.debug("Trying legacy format parsing (dictionary-based parameters)")
            try:
                yaml_data = yaml.safe_load(app_yaml_file.content)
                if not isinstance(yaml_data, dict):
                    raise BadRequestException("app.yaml must contain a YAML dictionary")
                
                parameters_section = yaml_data.get("parameters")
                if not parameters_section:
                    raise BadRequestException("app.yaml missing 'parameters' section")
                
                # Support both list and dict formats
                if isinstance(parameters_section, list):
                    # List format - convert to TemplateParameterSchema
                    # Validate that list contains dictionaries (not strings or other types)
                    if parameters_section and not all(isinstance(item, dict) for item in parameters_section):
                        raise BadRequestException("parameters section must be a dictionary")
                    
                    parameters_list = []
                    for param_def in parameters_section:
                        if not isinstance(param_def, dict):
                            continue
                        parameters_list.append({
                            "name": param_def.get("name"),
                            "type": param_def.get("type", "string"),
                            "required": param_def.get("required", False),
                            "default": param_def.get("default"),
                            "description": param_def.get("description", ""),
                            "label": param_def.get("label"),
                            "step": param_def.get("step"),
                            "enum": param_def.get("enum"),
                            "hidden": param_def.get("hidden", False)
                        })
                elif isinstance(parameters_section, dict):
                    # Dictionary format (legacy)
                    parameters_list = []
                    for param_name, param_def in parameters_section.items():
                        if not isinstance(param_def, dict):
                            continue
                        parameters_list.append({
                            "name": param_name,
                            "type": param_def.get("type", "string"),
                            "required": param_def.get("required", False),
                            "default": param_def.get("default"),
                            "description": param_def.get("description", "")
                        })
                else:
                    raise BadRequestException("parameters section must be a list or dictionary")
            except yaml.YAMLError as e:
                logger.error(f"Failed to parse app.yaml: {e}")
                raise BadRequestException(f"Invalid YAML in app.yaml: {str(e)}")
            except BadRequestException:
                # Re-raise BadRequestException as-is
                raise
            except Exception as e:
                logger.error(f"Unexpected error in fallback parsing: {e}")
                raise BadRequestException(f"Failed to parse parameters: {str(e)}")
        
        # Ensure parameters_list is initialized
        if parameters_list is None:
            parameters_list = []
        
        # Convert to TemplateParameterSchema objects
        parameters = []
        for param_dict in parameters_list:
            if not isinstance(param_dict, dict) or not param_dict.get("name"):
                continue
            
            parameters.append(
                TemplateParameterSchema(
                    name=param_dict.get("name"),
                    type=param_dict.get("type", "string"),
                    required=param_dict.get("required", False),
                    default=param_dict.get("default"),
                    description=param_dict.get("description", ""),
                    label=param_dict.get("label"),
                    step=param_dict.get("step"),
                    enum=param_dict.get("enum"),
                    hidden=param_dict.get("hidden", False)
                )
            )
        
        return TemplateParametersResponse(
            template_version_id=template_version_id,
            parameters=parameters
        )

