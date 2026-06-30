"""Course filter service for business logic."""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.exceptions import ConflictException, NotFoundException
from src.models.course_filter import CourseFilter
from src.repositories.course_filter_repository import CourseFilterRepository
from src.schemas.course_filter import CourseFilterCreate, CourseFilterUpdate

logger = logging.getLogger(__name__)


class CourseFilterService:
    """Service for course-filter business logic."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = CourseFilterRepository(db)

    def list_filters(
        self,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> tuple[list[CourseFilter], int]:
        return self.repo.get_all_filtered(skip=skip, limit=limit, search=search)

    def get_filter(self, filter_id: str | UUID) -> CourseFilter:
        instance = self.repo.get_by_id(filter_id)
        if not instance:
            raise NotFoundException(f"CourseFilter with ID {filter_id} not found")
        return instance

    def create_filter(self, data: CourseFilterCreate) -> CourseFilter:
        """Create a filter; rejects duplicate ``name`` with a 409.

        Vor-Check fängt den häufigen Fall sauber ab; die DB-Constraint bleibt
        als Race-Schutz und wird ebenfalls auf 409 gemappt.
        """
        if self.repo.get_by_name(data.name):
            raise ConflictException(f"Course filter with name '{data.name}' already exists")

        try:
            return self.repo.create(name=data.name)
        except IntegrityError as e:
            self.db.rollback()
            # ``extra={"name": ...}`` would collide with ``LogRecord.name``
            # and raise inside logging.makeRecord. Use a distinct key.
            logger.warning(
                "Unique violation on course_filters.name (race)",
                extra={"filter_name": data.name, "error": str(getattr(e, "orig", e))},
            )
            raise ConflictException(
                f"Course filter with name '{data.name}' already exists"
            )

    def update_filter(self, filter_id: str | UUID, data: CourseFilterUpdate) -> CourseFilter:
        instance = self.get_filter(filter_id)

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return instance

        new_name = update_data.get("name")
        if new_name and new_name != instance.name:
            existing = self.repo.get_by_name(new_name)
            if existing and existing.id != instance.id:
                raise ConflictException(
                    f"Course filter with name '{new_name}' already exists"
                )

        try:
            updated = self.repo.update(filter_id, **update_data)
        except IntegrityError as e:
            self.db.rollback()
            logger.warning(
                "Unique violation on course_filters.name during update (race)",
                extra={"id": str(filter_id), "filter_name": new_name, "error": str(getattr(e, "orig", e))},
            )
            raise ConflictException(
                f"Course filter with name '{new_name}' already exists"
            )
        return updated or instance

    def delete_filter(self, filter_id: str | UUID) -> bool:
        self.get_filter(filter_id)
        return self.repo.delete(filter_id)
