"""Admin-only /lecturers endpoints.

Provides three read/write operations against the User table filtered to
lecturers (= users that own templates or OpenStack projects). All routes
require the ``admin`` realm role — enforced by the router-level guard so
individual handlers don't repeat it.

The DELETE handler kicks off an async cascade via
``src.tasks.lecturer_tasks.cascade_delete_lecturer`` and returns 202 with
the task id. See that task for the exact ordering + bail-out rules.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from src.core.dependencies import CurrentUser, DBSession, RequestID, require_roles
from src.core.response_builder import ResponseBuilder
from src.models.user import UserRole
from src.schemas.lecturer import (
    LecturerDeleteResponse,
    LecturerDetail,
    LecturerListItem,
)
from src.services.lecturer_service import LecturerService
from src.tasks.lecturer_tasks import cascade_delete_lecturer
router = APIRouter(
    prefix="/lecturers",
    tags=["lecturers"],
    # Admin-only across the board — see module docstring for rationale.
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)


@router.get("")
async def list_lecturers(
    db: DBSession,
    request_id: RequestID,
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Page size (max 200)"),
    search: str | None = Query(
        None,
        description="Case-insensitive substring match against display_name/email/username",
    ),
):
    """List users who own at least one template or one OpenStack project.

    Rows carry aggregate counts (templates / deployments / OSPs) so the
    admin dashboard can render the list without a second round-trip per
    row.
    """
    service = LecturerService(db)
    # The paginated response helper thinks in 1-indexed pages, but we
    # expose skip/limit for consistency with the other admin endpoints.
    # Compute the page number the helper needs from skip/limit.
    page = (skip // limit) + 1 if limit else 1
    rows, total = service.list_lecturers(skip=skip, limit=limit, search=search)

    payload = [LecturerListItem(**r).model_dump(mode="json") for r in rows]
    return ResponseBuilder.paginated(
        data=payload,
        page=page,
        page_size=limit,
        total=total,
        message=f"Retrieved {len(payload)} lecturer(s)",
        request_id=request_id,
    )


@router.get("/{user_id}")
async def get_lecturer(
    user_id: str,
    db: DBSession,
    request_id: RequestID,
):
    """Detail view: list-row fields + the full owned/deployed resource
    lists (so the admin can review before hitting DELETE)."""
    service = LecturerService(db)
    detail = service.get_lecturer(user_id)
    return ResponseBuilder.success(
        data=LecturerDetail(**detail).model_dump(mode="json"),
        message="Lecturer detail retrieved",
        request_id=request_id,
    )


@router.delete("/{user_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_lecturer(
    user_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """Enqueue cascade delete of a lecturer and all their resources.

    Returns 202 with the Celery task id. The actual work — Heat teardown,
    template + OSP + user removal — happens asynchronously and can be
    monitored via the deployment log stream. An admin cannot delete their
    own account (guarded up-front)."""
    service = LecturerService(db)
    summary = service.preflight_delete(user_id=user_id, requesting_user_id=user["user_id"])

    async_result = cascade_delete_lecturer.delay(user_id)
    payload = LecturerDeleteResponse(
        task_id=async_result.id,
        user_id=user_id,
        deployment_count=summary["deployment_count"],
        template_count=summary["template_count"],
    )
    return ResponseBuilder.success(
        data=payload.model_dump(mode="json"),
        message="Lecturer cascade delete enqueued",
        request_id=request_id,
        status_code=status.HTTP_202_ACCEPTED,
    )
