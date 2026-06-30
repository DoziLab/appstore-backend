"""Course filter API endpoints.

Admin-verwaltete Filter-Strings (Frontend-Chips), gegen die Kursnamen client-
seitig gematcht werden. Lese-Zugriff ist für alle eingeloggten User offen,
damit das Frontend die Chip-Leiste rendern kann; Schreiben ist Admin-only.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from src.core.dependencies import (
    CurrentUser,
    DBSession,
    Pagination,
    RequestID,
    require_roles,
)
from src.core.response_builder import ResponseBuilder
from src.models.user import UserRole
from src.schemas.course_filter import (
    CourseFilterCreate,
    CourseFilterResponse,
    CourseFilterUpdate,
)
from src.services.course_filter_service import CourseFilterService

router = APIRouter(prefix="/course-filters", tags=["course-filters"])


@router.get("", response_model=None)
async def list_course_filters(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    search: Optional[str] = Query(None, description="Substring-Suche auf name"),
):
    """List course filters. Open to any authenticated user (frontend needs them)."""
    service = CourseFilterService(db)
    rows, total = service.list_filters(
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
        search=search,
    )

    payload = [
        CourseFilterResponse.model_validate(row).model_dump(mode="json") for row in rows
    ]

    return ResponseBuilder.paginated(
        data=payload,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        message="Course filters retrieved successfully",
        request_id=request_id,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
async def create_course_filter(
    data: CourseFilterCreate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Create a new course filter (admin only)."""
    service = CourseFilterService(db)
    instance = service.create_filter(data)

    return ResponseBuilder.created(
        data=CourseFilterResponse.model_validate(instance).model_dump(mode="json"),
        message="Course filter created successfully",
        request_id=request_id,
    )


@router.patch(
    "/{filter_id}",
    response_model=None,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
async def update_course_filter(
    filter_id: UUID,
    data: CourseFilterUpdate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Rename a course filter (admin only)."""
    service = CourseFilterService(db)
    instance = service.update_filter(filter_id=filter_id, data=data)

    return ResponseBuilder.success(
        data=CourseFilterResponse.model_validate(instance).model_dump(mode="json"),
        message="Course filter updated successfully",
        request_id=request_id,
    )


@router.delete(
    "/{filter_id}",
    status_code=status.HTTP_200_OK,
    response_model=None,
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
async def delete_course_filter(
    filter_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Delete a course filter (admin only)."""
    service = CourseFilterService(db)
    service.delete_filter(filter_id=filter_id)

    return ResponseBuilder.success(
        data=None,
        message="Course filter deleted successfully",
        request_id=request_id,
    )
