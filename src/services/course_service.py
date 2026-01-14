"""Course service for business logic."""
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.models.course import Course
from src.repositories.course_repository import CourseRepository
from src.schemas.course import CourseCreate, CourseUpdate
from src.core.exceptions import NotFoundException, ForbiddenException


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
        course_data: CourseCreate,
        lecturer_id: str
    ) -> Course:
        """Create a new course.
        
        The authenticated lecturer becomes the course owner.
        
        Args:
            course_data: Course creation data
            lecturer_id: ID of the lecturer creating the course
            
        Returns:
            Created course
        """
        course = self.course_repo.create(
            name=course_data.name,
            semester=course_data.semester,
            lecturer_id=lecturer_id,
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
        lecturer_id: Optional[str] = None,
        semester: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Course], int]:
        """List courses with filters and pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            lecturer_id: Filter by lecturer ID
            semester: Filter by semester
            search: Search term for course name
            
        Returns:
            Tuple of (list of courses, total count)
        """
        return self.course_repo.get_all_filtered(
            skip=skip,
            limit=limit,
            lecturer_id=lecturer_id,
            semester=semester,
            search=search,
        )

    def update_course(
        self,
        course_id: str | UUID,
        course_data: CourseUpdate,
        current_user_id: str,
    ) -> Course:
        """Update an existing course.
        
        Only the course lecturer can update the course.
        
        Args:
            course_id: Course ID
            course_data: Course update data
            current_user_id: ID of the user making the request
            
        Returns:
            Updated course
            
        Raises:
            NotFoundException: If course not found
            ForbiddenException: If user is not the course lecturer
        """
        course = self.get_course(course_id)
        
        # Only the course lecturer can update
        if course.lecturer_id != current_user_id:
            raise ForbiddenException("Only the course lecturer can update this course")
        
        # Build update dict with only provided fields
        update_data = course_data.model_dump(exclude_unset=True)
        
        if not update_data:
            return course
        
        updated_course = self.course_repo.update(str(course_id), **update_data)
        return updated_course

    def delete_course(
        self,
        course_id: str | UUID,
        current_user_id: str,
    ) -> bool:
        """Delete a course.
        
        Only the course lecturer can delete the course.
        
        Args:
            course_id: Course ID
            current_user_id: ID of the user making the request
            
        Returns:
            True if deleted successfully
            
        Raises:
            NotFoundException: If course not found
            ForbiddenException: If user is not the course lecturer
        """
        course = self.get_course(course_id)
        
        # Only the course lecturer can delete
        if course.lecturer_id != current_user_id:
            raise ForbiddenException("Only the course lecturer can delete this course")
        
        return self.course_repo.delete(str(course_id))

    def get_lecturer_courses(self, lecturer_id: str | UUID) -> list[Course]:
        """Get all courses for a specific lecturer.
        
        Args:
            lecturer_id: Lecturer user ID
            
        Returns:
            List of courses for the lecturer
        """
        return self.course_repo.get_by_lecturer(lecturer_id)
