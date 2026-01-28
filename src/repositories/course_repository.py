"""Course repository for database operations."""
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from src.models.course import Course
from src.repositories.base_repository import BaseRepository


class CourseRepository(BaseRepository[Course]):
    """Repository for Course database operations."""

    def __init__(self, db: Session):
        """Initialize CourseRepository with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        super().__init__(Course, db)

    def _apply_filters(
        self,
        query,
        search: Optional[str] = None,
    ):
        """Apply common filters to a query."""
        if search:
            query = query.filter(
                (self.model.name.ilike(f"%{search}%")) |
                (self.model.keycloak_course_id.ilike(f"%{search}%"))
            )
        return query

    def get_all_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> tuple[list[Course], int]:
        """Get all courses with filters and pagination.
        
        Args:
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            search: Search term for course name or keycloak_course_id
            
        Returns:
            Tuple of (list of courses, total count)
        """
        base_query = self._apply_filters(
            self.db.query(self.model),
            search
        )
        
        total = base_query.count()
        
        courses = (
            base_query
            .options(joinedload(self.model.deployments))
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        
        return courses, total
