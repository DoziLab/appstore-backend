"""Template repository for database operations."""
from typing import Optional
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.models.template import Template, TemplateVisibility, TemplateApprovalStatus
from src.repositories.base_repository import BaseRepository


class TemplateRepository(BaseRepository[Template]):
    """Repository for Template database operations."""

    def __init__(self, db: Session):
        """Initialize TemplateRepository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        super().__init__(Template, db)

    def get_all_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[TemplateApprovalStatus] = None,
        visibility: Optional[TemplateVisibility] = None,
        owner_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Template], int]:
        """Get all templates with filters and pagination.
        
        Args:
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            status: Filter by approval status
            visibility: Filter by visibility (private/public)
            owner_id: Filter by owner ID
            search: Search term for name/description
            
        Returns:
            Tuple of (list of templates, total count)
        """
        query = self.db.query(self.model)
        
        # Apply filters
        if status:
            query = query.filter(self.model.approval_status == status)
        
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
        
        # Get total count before pagination
        total = query.count()
        
        # Apply pagination
        templates = query.offset(skip).limit(limit).all()
        
        return templates, total

    def get_by_owner(self, owner_id: str | UUID) -> list[Template]:
        """Get all templates owned by a specific user.
        
        Args:
            owner_id: ID of the template owner
            
        Returns:
            List of templates owned by the user
        """
        return self.db.query(self.model).filter(
            self.model.owner_id == str(owner_id)
        ).all()

    def update_approval_status(
        self,
        template_id: str | UUID,
        status: TemplateApprovalStatus
    ) -> Optional[Template]:
        """Update template approval status.
        
        Args:
            template_id: ID of the template
            status: New approval status
            
        Returns:
            Updated template or None if not found
        """
        template = self.get_by_id(template_id)
        if template:
            return self.update(template_id, approval_status=status)
        return None
