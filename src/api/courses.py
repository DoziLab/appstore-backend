"""Course API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, status, Query, Depends

from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination, CurrentUser
from src.core.auth import require_roles
from src.core.exceptions import NotFoundException, ForbiddenException
from src.schemas.course import CourseCreate, CourseUpdate, CourseResponse, CourseGroupCreate, CourseGroupResponse, CourseMemberResponse, GroupMemberAdd
from src.services.course_service import CourseService
from src.models.user import UserRole
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.group_member import GroupMember
from sqlalchemy.orm import joinedload


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
    search: Optional[str] = Query(None, description="Search in course name or Keycloak course ID"),
):
    """List all courses with optional filters and pagination.
    
    Supports filtering by:
    - Search term (searches course name or keycloak_course_id)
    
    Returns paginated results with total count.
    """
    service = CourseService(db)
    
    courses, total = service.list_courses(
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
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
    
    Requires authentication. Course is identified by keycloak_course_id.
    """
    service = CourseService(db)
    
    course = service.create_course(course_data)
    
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
    
    Supports partial updates - only provided fields are updated.
    """
    service = CourseService(db)
    
    course = service.update_course(
        course_id=course_id,
        course_data=course_data,
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
    
    This will permanently remove the course.
    """
    service = CourseService(db)
    
    service.delete_course(course_id=course_id)
    
    return ResponseBuilder.success(
        data=None,
        message="Course deleted successfully",
        request_id=request_id,
    )


@router.get("/{course_id}/members", response_model=None)
async def list_course_members(
    course_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """List all members (students) for a specific course.
    
    Authorization: ADMIN or LECTURER
    """
    service = CourseService(db)
    
    # Verify course exists
    course = service.get_course(course_id)
    
    # Get course members with user information
    members = (
        db.query(CourseMember)
        .options(joinedload(CourseMember.user))
        .filter(CourseMember.course_id == str(course_id))
        .filter(CourseMember.left_at.is_(None))  # Only active members
        .order_by(CourseMember.joined_at.asc())
        .all()
    )
    
    # Build response with user info from token (we only have user_id in DB)
    member_responses = []
    for member in members:
        member_data = CourseMemberResponse.model_validate(member).model_dump(mode="json")
        # Add user_id for frontend reference
        member_data["user_id"] = member.user_id
        member_responses.append(member_data)
    
    return ResponseBuilder.success(
        data=member_responses,
        message="Course members retrieved successfully",
        request_id=request_id,
    )


@router.get("/{course_id}/groups", response_model=None)
async def list_course_groups(
    course_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """List all groups for a specific course.
    
    Authorization: ADMIN or LECTURER
    """
    service = CourseService(db)
    
    # Verify course exists
    course = service.get_course(course_id)
    
    # Get groups for this course
    groups = db.query(CourseGroup).filter(CourseGroup.course_id == str(course_id)).order_by(CourseGroup.created_at.asc()).all()
    
    group_responses = [
        CourseGroupResponse.model_validate(group).model_dump(mode="json")
        for group in groups
    ]
    
    return ResponseBuilder.success(
        data=group_responses,
        message="Course groups retrieved successfully",
        request_id=request_id,
    )


@router.post("/{course_id}/groups", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_course_group(
    course_id: UUID,
    group_data: CourseGroupCreate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Create a new group for a course.
    
    Authorization: ADMIN or LECTURER
    
    Request Body:
    {
        "name": "Group A"
    }
    """
    service = CourseService(db)
    
    # Verify course exists
    course = service.get_course(course_id)
    
    # Create the group
    group = CourseGroup(
        course_id=str(course_id),
        name=group_data.name,
    )
    
    db.add(group)
    db.commit()
    db.refresh(group)
    
    group_response = CourseGroupResponse.model_validate(group).model_dump(mode="json")
    
    return ResponseBuilder.created(
        data=group_response,
        message="Course group created successfully",
        request_id=request_id,
    )


@router.get("/{course_id}/groups/{group_id}/members", response_model=None)
async def list_group_members(
    course_id: UUID,
    group_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """List all members of a specific group.
    
    Authorization: ADMIN or LECTURER
    """
    service = CourseService(db)
    
    # Verify course exists
    course = service.get_course(course_id)
    
    # Verify group exists and belongs to course
    group = db.query(CourseGroup).filter(
        CourseGroup.id == str(group_id),
        CourseGroup.course_id == str(course_id)
    ).first()
    
    if not group:
        raise NotFoundException(f"Group with ID {group_id} not found in course {course_id}")
    
    # Get group members with course member and user information
    group_members = (
        db.query(GroupMember)
        .options(
            joinedload(GroupMember.course_member).joinedload(CourseMember.user)
        )
        .filter(GroupMember.group_id == str(group_id))
        .order_by(GroupMember.joined_at.asc())
        .all()
    )
    
    # Build response
    member_responses = []
    for gm in group_members:
        member_data = {
            "id": gm.id,
            "group_id": gm.group_id,
            "course_member_id": gm.course_member_id,
            "user_id": gm.course_member.user_id,
            "joined_at": gm.joined_at.isoformat() if gm.joined_at else None,
        }
        member_responses.append(member_data)
    
    return ResponseBuilder.success(
        data=member_responses,
        message="Group members retrieved successfully",
        request_id=request_id,
    )


@router.post("/{course_id}/groups/{group_id}/members", status_code=status.HTTP_201_CREATED, response_model=None)
async def add_group_members(
    course_id: UUID,
    group_id: UUID,
    member_data: GroupMemberAdd,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Add members (course_member_ids) to a group.
    
    Only the course lecturer can add members to groups.
    
    Authorization: Course lecturer or ADMIN
    
    Request Body:
    {
        "member_ids": ["course_member_id_1", "course_member_id_2"]
    }
    """
    member_ids = member_data.member_ids
    
    service = CourseService(db)
    
    # Verify course exists
    course = service.get_course(course_id)
    
    # Verify group exists and belongs to course
    group = db.query(CourseGroup).filter(
        CourseGroup.id == str(group_id),
        CourseGroup.course_id == str(course_id)
    ).first()
    
    if not group:
        raise NotFoundException(f"Group with ID {group_id} not found in course {course_id}")
    
    # Verify all course members exist and belong to the course
    course_members = (
        db.query(CourseMember)
        .filter(
            CourseMember.id.in_(member_ids),
            CourseMember.course_id == str(course_id),
            CourseMember.left_at.is_(None)  # Only active members
        )
        .all()
    )
    
    if len(course_members) != len(member_ids):
        raise NotFoundException("Some course members not found or not active")
    
    # Check for existing group memberships to avoid duplicates
    existing_members = (
        db.query(GroupMember)
        .filter(
            GroupMember.group_id == str(group_id),
            GroupMember.course_member_id.in_(member_ids)
        )
        .all()
    )
    
    existing_member_ids = {gm.course_member_id for gm in existing_members}
    
    # Create new group members
    new_members = []
    for course_member in course_members:
        if course_member.id not in existing_member_ids:
            group_member = GroupMember(
                group_id=str(group_id),
                course_member_id=course_member.id,
            )
            db.add(group_member)
            new_members.append(group_member)
    
    db.commit()
    
    # Refresh to get IDs
    for member in new_members:
        db.refresh(member)
    
    # Build response
    member_responses = []
    for gm in new_members:
        member_response_data = {
            "id": gm.id,
            "group_id": gm.group_id,
            "course_member_id": gm.course_member_id,
            "joined_at": gm.joined_at.isoformat() if gm.joined_at else None,
        }
        member_responses.append(member_response_data)
    
    return ResponseBuilder.created(
        data=member_responses,
        message=f"Added {len(new_members)} member(s) to group successfully",
        request_id=request_id,
    )
