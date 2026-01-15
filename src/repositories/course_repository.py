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
        lecturer_id: Optional[str] = None,
        semester: Optional[str] = None,
        search: Optional[str] = None,
    ):
        """Apply common filters to a query."""
        if lecturer_id:
            query = query.filter(self.model.lecturer_id == lecturer_id)
        if semester:
            query = query.filter(self.model.semester == semester)
        if search:
            query = query.filter(self.model.name.ilike(f"%{search}%"))
        return query

    def get_all_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        lecturer_id: Optional[str] = None,
        semester: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Course], int]:
        """Get all courses with filters and pagination.
        
        Args:
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            lecturer_id: Filter by lecturer ID
            semester: Filter by semester
            search: Search term for course name
            
        Returns:
            Tuple of (list of courses, total count)
        """
        base_query = self._apply_filters(
            self.db.query(self.model),
            lecturer_id, semester, search
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

    def get_by_lecturer(self, lecturer_id: str | UUID) -> list[Course]:
        """Get all courses owned by a specific lecturer.
        
        Args:
            lecturer_id: ID of the lecturer
            
        Returns:
            List of courses owned by the lecturer
        """
        return (
            self.db.query(self.model)
            .options(joinedload(self.model.deployments))
            .filter(self.model.lecturer_id == str(lecturer_id))
            .order_by(self.model.created_at.desc())
            .all()
        )

    def get_by_semester(self, semester: str) -> list[Course]:
        """Get all courses in a specific semester.
        
        Args:
            semester: Semester string (e.g., WS2024, SS2025)
            
        Returns:
            List of courses in the semester
        """
        return (
            self.db.query(self.model)
            .options(joinedload(self.model.deployments))
            .filter(self.model.semester == semester)
            .order_by(self.model.name)
            .all()
        )
