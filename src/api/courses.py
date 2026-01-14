"""Course API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, status, Query, Depends

from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination, CurrentUser
from src.core.auth import require_roles
from src.schemas.course import CourseCreate, CourseUpdate, CourseResponse
from src.services.course_service import CourseService
from src.models.user import UserRole


router = APIRouter(
    prefix="/courses",
    tags=["courses"],
    dependencies=[ Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)) ],  # All endpoints require at least LECTURER role
)


@router.get("", response_model=None)
async def list_courses(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    semester: Optional[str] = Query(None, description="Filter by semester (e.g., WS2024, SS2025)"),
    search: Optional[str] = Query(None, description="Search in course name"),
    lecturer_id: Optional[str] = Query(None, description="Filter by lecturer ID (admin only)"),
):
    """List all courses with optional filters and pagination.
    
    - Admins can see all courses and filter by lecturer_id
    - Non-admin users only see their own courses
    
    Supports filtering by:
    - Semester (e.g., WS2024, SS2025)
    - Lecturer ID (admin only)
    - Search term (searches course name)
    
    Returns paginated results with total count.
    """
    service = CourseService(db)
    
    # Check if user is admin
    realm_roles = current_user.get("realm_access", {}).get("roles", [])
    is_admin = "admin" in realm_roles
    
    # Non-admins can only see their own courses
    if is_admin:
        effective_lecturer_id = lecturer_id
    else:
        effective_lecturer_id = current_user["user_id"]
    
    courses, total = service.list_courses(
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
        lecturer_id=effective_lecturer_id,
        semester=semester,
        search=search,
    )
    
    course_responses = [
        CourseResponse.model_validate(course).model_dump(mode="json")
        for course in courses
    ]
    
    return ResponseBuilder.paginated(
        data=course_responses,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        message="Courses retrieved successfully",
        request_id=request_id,
    )


@router.get("/my", response_model=None)
async def list_my_courses(
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """List all courses for the authenticated lecturer.
    
    Returns all courses where the current user is the lecturer.
    """
    service = CourseService(db)
    
    courses = service.get_lecturer_courses(current_user["user_id"])
    
    course_responses = [
        CourseResponse.model_validate(course).model_dump(mode="json")
        for course in courses
    ]
    
    return ResponseBuilder.success(
        data=course_responses,
        message="Your courses retrieved successfully",
        request_id=request_id,
    )


@router.get("/{course_id}", response_model=None)
async def get_course(
    course_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Get a single course by ID.
    
    Returns complete course details including metadata and timestamps.
    """
    service = CourseService(db)
    course = service.get_course(str(course_id))
    
    course_response = CourseResponse.model_validate(course)
    
    return ResponseBuilder.success(
        data=course_response.model_dump(mode="json"),
        message="Course retrieved successfully",
        request_id=request_id,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_course(
    course_data: CourseCreate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Create a new course.
    
    Requires authentication. The authenticated user becomes the course lecturer.
    Each lecturer can create their own courses.
    """
    service = CourseService(db)
    
    course = service.create_course(course_data, lecturer_id=current_user["user_id"])
    
    course_response = CourseResponse.model_validate(course)
    
    return ResponseBuilder.created(
        data=course_response.model_dump(mode="json"),
        message="Course created successfully",
        request_id=request_id,
    )


@router.patch("/{course_id}", response_model=None)
async def update_course(
    course_id: UUID,
    course_data: CourseUpdate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Update an existing course.
    
    Only the course lecturer can update the course.
    Supports partial updates - only provided fields are updated.
    """
    service = CourseService(db)
    
    course = service.update_course(
        course_id=str(course_id),
        course_data=course_data,
        current_user_id=current_user["user_id"],
    )
    
    course_response = CourseResponse.model_validate(course)
    
    return ResponseBuilder.success(
        data=course_response.model_dump(mode="json"),
        message="Course updated successfully",
        request_id=request_id,
    )


@router.delete("/{course_id}", status_code=status.HTTP_200_OK, response_model=None)
async def delete_course(
    course_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Delete a course.
    
    Only the course lecturer can delete the course.
    This will permanently remove the course.
    """
    service = CourseService(db)
    
    service.delete_course(
        course_id=str(course_id),
        current_user_id=current_user["user_id"],
    )
    
    return ResponseBuilder.success(
        data=None,
        message="Course deleted successfully",
        request_id=request_id,
    )
