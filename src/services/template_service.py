"""Template service for business logic."""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersionApprovalStatus
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

    def _can_access_template(
        self,
        template: Template,
        user_id: Optional[str] = None,
        is_admin: bool = False
    ) -> bool:
        """Check if a user can access a template.

        Access rules (post per-version-approval refactor):
        - Admins can access any template.
        - Owners can always access their own templates.
        - Other users can access PUBLIC templates only if at least one version
          has been APPROVED. The per-version approval gate also applies on
          TemplateVersion (see TemplateVersionService._can_access_version),
          this is the template-level safety net so non-owners can't even see
          a public template until something on it is usable.

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

        if template.owner_id == user_id:
            return True

        if template.visibility != TemplateVisibility.PUBLIC:
            return False

        return self.template_repo.has_approved_version(template.id)

    def create_template(
        self,
        template_data: TemplateCreate,
        owner_id: str
    ) -> Template:
        """Create a new template.

        Templates are created with visibility 'private'. Approval lives on each
        TemplateVersion, not the Template itself.

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
            )

            logger.info(
                "Template created",
                extra={
                    "template_id": str(template.id),
                    "template_name": template.name,
                    "owner_id": owner_id,
                    "visibility": template_data.visibility,
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
        
        # Permission check using helper method
        if not self._can_access_template(template, user_id, is_admin):
            raise ForbiddenException("You do not have permission to view this template")
        
        return template

    def list_templates(
        self,
        skip: int = 0,
        limit: int = 100,
        visibility: Optional[str] = None,
        owner_id: Optional[str] = None,
        search: Optional[str] = None,
        user_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> tuple[list[Template], int]:
        """List templates with filters and pagination.

        Admins see all templates. Other users see their own templates plus
        public templates that have at least one APPROVED version. This filter
        is pushed into SQL so pagination totals stay accurate.
        """
        visibility_enum = TemplateVisibility(visibility) if visibility else None

        templates, total = self.template_repo.get_all_filtered(
            skip=skip,
            limit=limit,
            visibility=visibility_enum,
            owner_id=owner_id,
            search=search,
            visible_to_user_id=None if is_admin else user_id,
        )

        return templates, total

    def update_template(
        self,
        template_id: str | UUID,
        template_data: TemplateUpdate,
        user_id: str,
        is_admin: bool = False
    ) -> Template:
        """Update a template.

        Only template owners or admins can update templates. The same audience
        may change ``visibility``: switching ``private → public`` will reset
        the approval state of all versions to ``PENDING`` (admin review
        required before they become visible in the marketplace); switching
        ``public → private`` clears the approval state to NULL because the
        approval concept doesn't apply to private templates.

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
            # Visibility transition — owner-or-admin (already enforced above for
            # the whole update payload). The transition itself resets the per-
            # version approval state so the two views (marketplace vs. private)
            # don't get mixed up:
            #   private → public:  any version that was unset (NULL) flips to
            #                      PENDING, awaiting admin review.
            #   public → private:  every version's approval state is cleared
            #                      (NULL) plus approved_by/at/reason are wiped.
            if "visibility" in update_data:
                # Validate visibility value
                try:
                    new_visibility = TemplateVisibility(update_data["visibility"])
                except ValueError:
                    raise BadRequestException(f"Invalid visibility value: {update_data['visibility']}")

                if new_visibility != template.visibility:
                    if new_visibility == TemplateVisibility.PUBLIC:
                        # private → public: untyped versions enter the approval flow.
                        # Versions that already carry an explicit state (legacy
                        # data, or someone toggled back-and-forth) keep theirs.
                        for v in template.versions:
                            if v.approval_status is None:
                                v.approval_status = TemplateVersionApprovalStatus.PENDING
                    else:
                        # public → private: approval state is no longer meaningful.
                        for v in template.versions:
                            v.approval_status = None
                            v.approved_by_id = None
                            v.approved_at = None
                            v.rejection_reason = None

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
