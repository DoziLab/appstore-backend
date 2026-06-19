"""Course repository for database operations."""
from typing import Optional

from sqlalchemy.orm import Session, selectinload

from src.models.course import Course
from src.models.deployment import Deployment
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

    def _deployments_loader(self, openstack_project_id: Optional[str]):
        """Build the eager-load option for ``Course.deployments``.

        When ``openstack_project_id`` is set, only deployments belonging to that
        OpenStack project are eager-loaded into ``course.deployments``. We use
        ``selectinload`` (not ``joinedload``) so the embedded list is filtered
        cleanly via a separate ``WHERE deployment.course_id IN (...) AND
        deployment.openstack_project_id = ?`` query, instead of mixing courses
        and deployments into one row-set that ``and_()`` filters can't dedup.
        """
        if openstack_project_id is None:
            return selectinload(self.model.deployments)
        return selectinload(
            self.model.deployments.and_(
                Deployment.openstack_project_id == str(openstack_project_id)
            )
        )

    def get_all_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
        openstack_project_id: Optional[str] = None,
    ) -> tuple[list[Course], int]:
        """Get all courses with filters and pagination.

        Args:
            skip: Number of records to skip (offset)
            limit: Maximum number of records to return
            search: Search term for course name or keycloak_course_id
            openstack_project_id: If set, only deployments belonging to this
                OpenStack project (local DB id) are eager-loaded into
                ``course.deployments``. Courses themselves are not filtered.

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
            .options(self._deployments_loader(openstack_project_id))
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        return courses, total

    def get_by_id_with_deployments(
        self,
        course_id: str,
        openstack_project_id: Optional[str] = None,
    ) -> Optional[Course]:
        """Fetch a course by id with its deployments eager-loaded.

        Args:
            course_id: Course primary key.
            openstack_project_id: Same semantics as ``get_all_filtered`` —
                filters the embedded ``deployments`` collection only.

        Returns:
            The Course (with filtered deployments) or ``None`` if not found.
        """
        return (
            self.db.query(self.model)
            .options(self._deployments_loader(openstack_project_id))
            .filter(self.model.id == str(course_id))
            .first()
        )
