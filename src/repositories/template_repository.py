"""Template repository for database operations."""
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session, joinedload

from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.repositories.base_repository import BaseRepository


class TemplateRepository(BaseRepository[Template]):
    """Repository for Template database operations."""

    def __init__(self, db: Session):
        """Initialize TemplateRepository with database session."""
        super().__init__(Template, db)

    def get_by_id(self, id):
        """Get a template by ID with the owner relationship eager-loaded.

        Override of BaseRepository.get_by_id so consumers always have access
        to ``template.owner.display_name`` without an extra round-trip.
        """
        return (
            self.db.query(self.model)
            .options(joinedload(self.model.owner))
            .filter(self.model.id == str(id))
            .first()
        )

    @staticmethod
    def _has_approved_version_clause():
        """SQL EXISTS clause: template has at least one APPROVED version."""
        return exists().where(
            and_(
                TemplateVersion.template_id == Template.id,
                TemplateVersion.approval_status == TemplateVersionApprovalStatus.APPROVED,
            )
        )

    def has_approved_version(self, template_id: str | UUID) -> bool:
        """Return True if the template has at least one APPROVED version."""
        return self.db.query(
            self.db.query(TemplateVersion)
            .filter(
                TemplateVersion.template_id == str(template_id),
                TemplateVersion.approval_status == TemplateVersionApprovalStatus.APPROVED,
            )
            .exists()
        ).scalar()

    def get_all_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        visibility: Optional[TemplateVisibility] = None,
        owner_id: Optional[str] = None,
        search: Optional[str] = None,
        visible_to_user_id: Optional[str] = None,
    ) -> tuple[list[Template], int]:
        """Get all templates with filters and pagination.

        When ``visible_to_user_id`` is set, the result is restricted to templates
        the viewer is allowed to see: their own templates *or* public templates
        that have at least one APPROVED version. Pass ``None`` for admins / when
        the caller has already gated access elsewhere.
        """
        query = self.db.query(self.model).options(joinedload(self.model.owner))

        if visibility:
            query = query.filter(self.model.visibility == visibility)

        if owner_id:
            query = query.filter(self.model.owner_id == owner_id)

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    self.model.name.ilike(search_term),
                    self.model.description.ilike(search_term)
                )
            )

        if visible_to_user_id is not None:
            query = query.filter(
                or_(
                    self.model.owner_id == visible_to_user_id,
                    and_(
                        self.model.visibility == TemplateVisibility.PUBLIC,
                        self._has_approved_version_clause(),
                    ),
                )
            )

        total = query.count()
        templates = query.offset(skip).limit(limit).all()
        return templates, total

    def get_by_owner(self, owner_id: str | UUID) -> list[Template]:
        """Get all templates owned by a specific user."""
        return self.db.query(self.model).filter(
            self.model.owner_id == str(owner_id)
        ).all()
