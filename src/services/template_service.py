"""Template service for business logic."""
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.repositories.template_repository import TemplateRepository
from src.schemas.template import TemplateCreate, TemplateUpdate
from src.core.exceptions import NotFoundException, ForbiddenException


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
        
        Templates are created with initial status 'pending' and must be
        approved before becoming publicly available.
        
        Args:
            template_data: Template creation data
            owner_id: ID of the user creating the template
            
        Returns:
            Created template
        """
        template = self.template_repo.create(
            name=template_data.name,
            description=template_data.description,
            repo_url=template_data.repo_url,
            visibility=template_data.visibility,
            owner_id=owner_id,
            approval_status=TemplateApprovalStatus.PENDING
        )
        return template

    def get_template(self, template_id: str | UUID) -> Template:
        """Get a template by ID.
        
        Args:
            template_id: Template ID
            
        Returns:
            Template instance
            
        Raises:
            NotFoundException: If template not found
        """
        template = self.template_repo.get_by_id(template_id)
        if not template:
            raise NotFoundException(f"Template with ID {template_id} not found")
        return template

    def list_templates(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        visibility: Optional[str] = None,
        owner_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Template], int]:
        """List templates with filters and pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            status: Filter by approval status (pending/approved/rejected/deprecated)
            visibility: Filter by visibility (private/public)
            owner_id: Filter by owner ID
            search: Search term for name/description
            
        Returns:
            Tuple of (list of templates, total count)
        """
        # Convert string enums to enum types if provided
        status_enum = TemplateApprovalStatus(status) if status else None
        visibility_enum = TemplateVisibility(visibility) if visibility else None
        
        return self.template_repo.get_all_filtered(
            skip=skip,
            limit=limit,
            status=status_enum,
            visibility=visibility_enum,
            owner_id=owner_id,
            search=search,
        )

    def update_template(
        self,
        template_id: str | UUID,
        template_data: TemplateUpdate,
        user_id: str,
        is_admin: bool = False
    ) -> Template:
        """Update a template.
        
        Only template owners or admins can update templates.
        
        Args:
            template_id: Template ID
            template_data: Template update data
            user_id: ID of user performing the update
            is_admin: Whether the user is an admin
            
        Returns:
            Updated template
            
        Raises:
            NotFoundException: If template not found
            ForbiddenException: If user is not owner or admin
        """
        template = self.get_template(template_id)
        
        # Permission check: only owner or admin can update
        if template.owner_id != user_id and not is_admin:
            raise ForbiddenException("You do not have permission to update this template")
        
        # Prepare update data (only include fields that were provided)
        update_data = template_data.model_dump(exclude_unset=True)
        
        if not update_data:
            return template
        
        uuid_id = template_id if isinstance(template_id, UUID) else UUID(str(template_id))
        updated_template = self.template_repo.update(uuid_id, **update_data)
        if not updated_template:
            raise NotFoundException(f"Template with ID {template_id} not found")
        
        return updated_template

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
        template = self.get_template(template_id)
        
        # Permission check: only owner or admin can delete
        if template.owner_id != user_id and not is_admin:
            raise ForbiddenException("You do not have permission to delete this template")
        
        uuid_id = template_id if isinstance(template_id, UUID) else UUID(str(template_id))
        success = self.template_repo.delete(uuid_id)
        if not success:
            raise NotFoundException(f"Template with ID {template_id} not found")

    def approve_template(self, template_id: str | UUID) -> Template:
        """Approve a template for public use.
        
        Args:
            template_id: Template ID
            
        Returns:
            Updated template
            
        Raises:
            NotFoundException: If template not found
        """
        updated = self.template_repo.update_approval_status(
            template_id,
            TemplateApprovalStatus.APPROVED
        )
        if not updated:
            raise NotFoundException(f"Template with ID {template_id} not found")
        return updated

    def reject_template(self, template_id: str | UUID) -> Template:
        """Reject a template.
        
        Args:
            template_id: Template ID
            
        Returns:
            Updated template
            
        Raises:
            NotFoundException: If template not found
        """
        updated = self.template_repo.update_approval_status(
            template_id,
            TemplateApprovalStatus.REJECTED
        )
        if not updated:
            raise NotFoundException(f"Template with ID {template_id} not found")
        return updated
