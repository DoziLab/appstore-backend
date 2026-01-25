"""Template service for business logic."""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.repositories.template_repository import TemplateRepository
from src.schemas.template import TemplateCreate, TemplateUpdate
from src.core.exceptions import NotFoundException, ForbiddenException, BadRequestException

logger = logging.getLogger(__name__)


class TemplateService:
    """Service for template business logic."""

    def __init__(self, db: Session):
        """Initialize TemplateService with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.template_repo = TemplateRepository(db)

    def create_template(
        self,
        template_data: TemplateCreate,
        owner_id: str
    ) -> Template:
        """Create a new template.
        
        Templates are created with visibility 'private' and approval status 'pending'.
        They must be approved by an admin before becoming publicly available.
        
        Args:
            template_data: Template creation data
            owner_id: ID of the user creating the template
            
        Returns:
            Created template
        """
        try:
            template = self.template_repo.create(
                name=template_data.name,
                description=template_data.description,
                repo_url=template_data.repo_url,
                icon_url=template_data.icon_url,
                visibility=TemplateVisibility.PRIVATE,
                owner_id=owner_id,
                approval_status=TemplateApprovalStatus.PENDING
            )
            
            logger.info(
                "Template created",
                extra={
                    "template_id": str(template.id),
                    "template_name": template.name,
                    "owner_id": owner_id,
                    "visibility": template_data.visibility,
                    "approval_status": TemplateApprovalStatus.PENDING.value
                }
            )
            
            return template
        except Exception as e:
            logger.error(
                f"Error creating template: {e}",
                extra={
                    "template_name": template_data.name,
                    "owner_id": owner_id
                },
                exc_info=True
            )
            raise

    def get_template(
        self,
        template_id: str | UUID,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> Template:
        """Get a template by ID.
        
        Admins can view any template.
        Lecturers can only view approved public templates or their own templates.
        
        Args:
            template_id: Template ID
            user_id: ID of the requesting user (for permission check)
            is_admin: Whether the requesting user is an admin
            
        Returns:
            Template instance
            
        Raises:
            NotFoundException: If template not found
            ForbiddenException: If user lacks permission to view template
        """
        template = self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundException(f"Template with ID {template_id} not found")
        
        # Permission check for non-admins
        if not is_admin and user_id:
            # Non-admins can only see:
            # 1. Their own templates (any status)
            # 2. Approved public templates
            is_owner = template.owner_id == user_id
            is_public_approved = (
                template.visibility == TemplateVisibility.PUBLIC and
                template.approval_status == TemplateApprovalStatus.APPROVED
            )
            
            if not is_owner and not is_public_approved:
                raise ForbiddenException("You do not have permission to view this template")
        
        return template

    def list_templates(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        visibility: Optional[str] = None,
        owner_id: Optional[str] = None,
        search: Optional[str] = None,
        user_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> tuple[list[Template], int]:
        """List templates with filters and pagination.
        
        Admins see all templates.
        Lecturers see only approved public templates and their own templates.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            status: Filter by approval status (pending/approved/rejected/deprecated)
            visibility: Filter by visibility (private/public)
            owner_id: Filter by owner ID
            search: Search term for name/description
            user_id: ID of the requesting user (for permission filtering)
            is_admin: Whether the requesting user is an admin
            
        Returns:
            Tuple of (list of templates, total count)
        """
        # Convert string enums to enum types if provided
        status_enum = TemplateApprovalStatus(status) if status else None
        visibility_enum = TemplateVisibility(visibility) if visibility else None
        
        # Get filtered templates from repository
        templates, total = self.template_repo.get_all_filtered(
            skip=skip,
            limit=limit,
            status=status_enum,
            visibility=visibility_enum,
            owner_id=owner_id,
            search=search,
        )
        
        # Apply permission filtering for non-admins
        if not is_admin and user_id:
            filtered_templates = []
            for template in templates:
                # Lecturers can see:
                # 1. Their own templates (any status, any visibility)
                # 2. Approved public templates
                is_owner = template.owner_id == user_id
                is_public_approved = (
                    template.visibility == TemplateVisibility.PUBLIC and
                    template.approval_status == TemplateApprovalStatus.APPROVED
                )
                
                if is_owner or is_public_approved:
                    filtered_templates.append(template)
            
            templates = filtered_templates
            total = len(filtered_templates)
        
        return templates, total

    def update_template(
        self,
        template_id: str | UUID,
        template_data: TemplateUpdate,
        user_id: str,
        is_admin: bool = False
    ) -> Template:
        """Update a template.
        
        Only template owners or admins can update templates.
        Only admins can change visibility.
        
        Args:
            template_id: Template ID
            template_data: Template update data
            user_id: ID of user performing the update
            is_admin: Whether the user is an admin
            
        Returns:
            Updated template
            
        Raises:
            NotFoundException: If template not found
            ForbiddenException: If user is not owner or admin, or non-admin tries to change visibility
        """
        template = self.get_template(template_id, user_id=user_id, is_admin=is_admin)
        
        # Permission check: only owner or admin can update
        if template.owner_id != user_id and not is_admin:
            logger.warning(
                "Unauthorized template update attempt",
                extra={
                    "template_id": str(template_id),
                    "owner_id": template.owner_id,
                    "attempting_user_id": user_id,
                    "is_admin": is_admin
                }
            )
            raise ForbiddenException("You do not have permission to update this template")
        
        # Prepare update data (only include fields that were provided)
        update_data = template_data.model_dump(exclude_unset=True)
        
        if not update_data:
            return template
        
        try:
            # Check if visibility is being changed
            if "visibility" in update_data:
                if not is_admin:
                    raise ForbiddenException("Only admins can change template visibility")
                
                # Validate visibility value
                try:
                    TemplateVisibility(update_data["visibility"])
                except ValueError:
                    raise BadRequestException(f"Invalid visibility value: {update_data['visibility']}")
            
            uuid_id = template_id if isinstance(template_id, UUID) else UUID(str(template_id))
            updated_template = self.template_repo.update(uuid_id, **update_data)
            if not updated_template:
                raise NotFoundException(f"Template with ID {template_id} not found")
            
            logger.info(
                "Template updated",
                extra={
                    "template_id": str(template_id),
                    "updated_by": user_id,
                    "updated_fields": list(update_data.keys())
                }
            )
            
            return updated_template
        except Exception as e:
            logger.error(
                f"Error updating template: {e}",
                extra={
                    "template_id": str(template_id),
                    "user_id": user_id
                },
                exc_info=True
            )
            raise

    def delete_template(
        self,
        template_id: str | UUID,
        user_id: str,
        is_admin: bool = False
    ) -> None:
        """Delete a template.
        
        Only template owners or admins can delete templates.
        
        Args:
            template_id: Template ID
            user_id: ID of user performing the deletion
            is_admin: Whether the user is an admin
            
        Raises:
            NotFoundException: If template not found
            ForbiddenException: If user is not owner or admin
        """
        template = self.get_template(template_id, user_id=user_id, is_admin=is_admin)
        
        # Permission check: only owner or admin can delete
        if template.owner_id != user_id and not is_admin:
            logger.warning(
                "Unauthorized template deletion attempt",
                extra={
                    "template_id": str(template_id),
                    "owner_id": template.owner_id,
                    "attempting_user_id": user_id,
                    "is_admin": is_admin
                }
            )
            raise ForbiddenException("You do not have permission to delete this template")
        
        try:
            uuid_id = template_id if isinstance(template_id, UUID) else UUID(str(template_id))
            success = self.template_repo.delete(uuid_id)
            if not success:
                raise NotFoundException(f"Template with ID {template_id} not found")
            
            logger.info(
                "Template deleted",
                extra={
                    "template_id": str(template_id),
                    "template_name": template.name,
                    "deleted_by": user_id
                }
            )
        except Exception as e:
            logger.error(
                f"Error deleting template: {e}",
                extra={
                    "template_id": str(template_id),
                    "user_id": user_id
                },
                exc_info=True
            )
            raise

    def approve_template(self, template_id: str | UUID) -> Template:
        """Approve a template for public use.
        
        Automatically sets approval_status to 'approved' and visibility to 'public'.
        
        Args:
            template_id: Template ID
            
        Returns:
            Updated template
            
        Raises:
            NotFoundException: If template not found
        """
        try:
            uuid_id = template_id if isinstance(template_id, UUID) else UUID(str(template_id))
            
            # Update both approval status and visibility
            updated = self.template_repo.update(
                uuid_id,
                approval_status=TemplateApprovalStatus.APPROVED,
                visibility=TemplateVisibility.PUBLIC
            )
            
            if not updated:
                raise NotFoundException(f"Template with ID {template_id} not found")
            
            logger.info(
                "Template approved",
                extra={
                    "template_id": str(template_id),
                    "template_name": updated.name,
                    "approval_status": TemplateApprovalStatus.APPROVED.value
                }
            )
            
            return updated
        except Exception as e:
            logger.error(
                f"Error approving template: {e}",
                extra={"template_id": str(template_id)},
                exc_info=True
            )
            raise

    def reject_template(self, template_id: str | UUID) -> Template:
        """Reject a template.
        
        Args:
            template_id: Template ID
            
        Returns:
            Updated template
            
        Raises:
            NotFoundException: If template not found
        """
        try:
            updated = self.template_repo.update_approval_status(
                template_id,
                TemplateApprovalStatus.REJECTED
            )
            if not updated:
                raise NotFoundException(f"Template with ID {template_id} not found")
            
            logger.info(
                "Template rejected",
                extra={
                    "template_id": str(template_id),
                    "template_name": updated.name,
                    "approval_status": TemplateApprovalStatus.REJECTED.value
                }
            )
            
            return updated
        except Exception as e:
            logger.error(
                f"Error rejecting template: {e}",
                extra={"template_id": str(template_id)},
                exc_info=True
            )
            raise
