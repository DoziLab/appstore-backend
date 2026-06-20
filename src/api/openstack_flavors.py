"""OpenStack flavors API endpoint.

Exposes the available Nova flavors (compute size offerings) for an
OpenStack project. Used by the frontend to resolve flavor *names*
(e.g. ``gp1.small``) into actual vCPU / RAM / disk numbers, instead
of the previously hardcoded ``*2 / *4 / *20`` multipliers in
``DeploymentDetailsPage.tsx`` and ``AdminMonitoring.tsx``.

Auth & project scoping mirror the ``/quotas`` endpoint:
- Lecturers may only read flavors for their own project.
- Admins may pass ``project_id`` or ``lecturer_id`` to read any project.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.core.dependencies import CurrentUser, DBSession, RequestID, require_roles
from src.core.exceptions import ForbiddenException, NotFoundException
from src.core.response_builder import ResponseBuilder
from src.models.user import UserRole
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.schemas.openstack_resources import FlavorsResponse
from src.services.openstack_resource_service import OpenstackResourceService

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/openstack",
    tags=["openstack"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],
)


@router.get(
    "/flavors",
    response_model=FlavorsResponse,
)
async def get_flavors(
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    lecturer_id: UUID | None = Query(
        None,
        description=(
            "Lecturer user ID (admin only). Each lecturer has exactly one project. "
            "If specified, returns flavors visible to that lecturer's project."
        ),
    ),
    project_id: UUID | None = Query(
        None,
        description=(
            "Project ID (optional, defaults to user's own project). "
            "Admins can specify any project ID."
        ),
    ),
):
    """Get the list of available Nova flavors for an OpenStack project.

    Returns one entry per flavor with ``id``, ``name``, ``vcpus``,
    ``ram_mb``, ``disk_gb``, ``ephemeral_gb`` and ``is_public``.

    Access Control:
    - LECTURER: only their own project
    - ADMIN: any project (via ``project_id`` or ``lecturer_id``)
    """
    user_id = user.get("user_id")
    if not user_id:
        raise ForbiddenException("User ID not found in authentication token")

    user_roles = user.get("roles", [])
    is_admin = UserRole.ADMIN.value in user_roles

    target_user_id: str = user_id
    project_id_str: str | None = None

    # Priority: lecturer_id > project_id > caller's own project
    if lecturer_id:
        if not is_admin:
            raise ForbiddenException("Only admins can specify lecturer_id")

        target_user_id = str(lecturer_id)
        project_repo = OpenstackProjectRepository(db)

        if not project_repo.user_exists(target_user_id):
            logger.warning(f"Lecturer not found: {lecturer_id}")
            raise NotFoundException(f"Lecturer with ID {lecturer_id} does not exist")

        lecturer_projects = project_repo.get_by_owner(target_user_id)
        if not lecturer_projects:
            logger.warning(f"No project found for lecturer: {lecturer_id}")
            raise NotFoundException(
                f"No OpenStack project found for lecturer with ID {lecturer_id}"
            )

        if len(lecturer_projects) > 1:
            logger.warning(
                f"Lecturer {lecturer_id} has {len(lecturer_projects)} projects (expected 1), using first one",
                extra={"lecturer_id": str(lecturer_id), "project_count": len(lecturer_projects)},
            )
        project_id_str = str(lecturer_projects[0].id)
    elif project_id:
        project_id_str = str(project_id)
        # Ownership check is delegated to the service via _get_project_for_user

    resource_service = OpenstackResourceService(db)
    flavors_data = resource_service.get_flavors(
        user_id=target_user_id,
        project_id=project_id_str,
        allow_admin_access=is_admin,
    )

    # owner_user_id is only surfaced to admins (consistent with /quotas)
    owner_user_id = flavors_data.get("owner_user_id") if is_admin else None

    response_data = FlavorsResponse.from_service_dict(flavors_data, owner_user_id=owner_user_id)

    return ResponseBuilder.success(
        data=response_data,
        message="Flavors retrieved successfully",
        request_id=request_id,
    )
