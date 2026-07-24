"""Course filter repository for database operations."""
from typing import Optional

from sqlalchemy.orm import Session

from src.models.course_filter import CourseFilter
from src.repositories.base_repository import BaseRepository


class CourseFilterRepository(BaseRepository[CourseFilter]):
    """Repository for CourseFilter database operations."""

    def __init__(self, db: Session):
        super().__init__(CourseFilter, db)

    def get_by_name(self, name: str) -> Optional[CourseFilter]:
        """Fetch a filter by its exact (case-sensitive) name."""
        return self.db.query(self.model).filter(self.model.name == name).first()

    def get_all_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> tuple[list[CourseFilter], int]:
        """List filters with optional substring search and pagination.

        Returns:
            Tuple of (rows, total count matching the search).
        """
        query = self.db.query(self.model)
        if search:
            query = query.filter(self.model.name.ilike(f"%{search}%"))

        total = query.count()
        rows = (
            query
            .order_by(self.model.name.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return rows, total
