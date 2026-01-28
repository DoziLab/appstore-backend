"""Course service for business logic."""
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.models.course import Course
from src.repositories.course_repository import CourseRepository
from src.schemas.course import CourseCreate, CourseUpdate
from src.core.exceptions import NotFoundException


class CourseService:
    """Service for course business logic."""

    def __init__(self, db: Session):
        """Initialize CourseService with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.course_repo = CourseRepository(db)

    def create_course(
        self,
        course_data: CourseCreate
    ) -> Course:
        """Create a new course.
        
        Args:
            course_data: Course creation data with name and keycloak_course_id
            
        Returns:
            Created course
        """
        course = self.course_repo.create(
            name=course_data.name,
            keycloak_course_id=course_data.keycloak_course_id,
        )
        return course

    def get_course(self, course_id: str | UUID) -> Course:
        """Get a course by ID.
        
        Args:
            course_id: Course ID
            
        Returns:
            Course instance
            
        Raises:
            NotFoundException: If course not found
        """
        course = self.course_repo.get_by_id(course_id)
        if not course:
            raise NotFoundException(f"Course with ID {course_id} not found")
        return course

    def list_courses(
        self,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> tuple[list[Course], int]:
        """List courses with filters and pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            search: Search term for course name or keycloak_course_id
            
        Returns:
            Tuple of (list of courses, total count)
        """
        return self.course_repo.get_all_filtered(
            skip=skip,
            limit=limit,
            search=search,
        )

    def update_course(
        self,
        course_id: UUID,
        course_data: CourseUpdate,
    ) -> Course | None:
        """Update an existing course.
        
        Args:
            course_id: Course ID
            course_data: Course update data
            
        Returns:
            Updated course
            
        Raises:
            NotFoundException: If course not found
        """
        course = self.get_course(course_id)
        
        # Build update dict with only provided fields
        update_data = course_data.model_dump(exclude_unset=True)
        
        if not update_data:
            return course
        
        updated_course = self.course_repo.update(course_id, **update_data)
        return updated_course

    def delete_course(
        self,
        course_id: UUID,
    ) -> bool:
        """Delete a course.
        
        Args:
            course_id: Course ID
            
        Returns:
            True if deleted successfully
            
        Raises:
            NotFoundException: If course not found
        """
        self.get_course(course_id)
        return self.course_repo.delete(course_id)

