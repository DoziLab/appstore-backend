"""Quotas API endpoints."""
import logging
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, require_roles, CurrentUser
from src.models.user import UserRole
from src.schemas.openstack_resources import QuotaResponse
from src.services.openstack_resource_service import OpenstackResourceService
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.core.exceptions import ForbiddenException, NotFoundException

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/quotas",
    tags=["quotas"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],
)


@router.get(
    "",
    response_model=QuotaResponse,
)
async def get_quotas(
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    lecturer_id: UUID | None = Query(None, description="Lecturer user ID (admin only). Each lecturer has exactly one project. If specified, returns quotas for that lecturer's project."),
    project_id: UUID | None = Query(None, description="Project ID (optional, defaults to user's own project). Admins can specify any project ID."),
    force_refresh: bool = Query(False, description="Force refresh from OpenStack (bypass cache)"),
):
    """Get quotas and usage for an OpenStack project.
    
    Returns quota limits, current usage, and available resources for:
    - Compute (instances, cores, RAM)
    - Network (floating IPs, networks, ports, etc.)
    - Volume (volumes, snapshots, storage)
    
    Access Control:
    - LECTURER: Can only view quotas for their own project
    - ADMIN: Can view quotas for any project by specifying project_id, or any lecturer by specifying lecturer_id
    
    Args:
        lecturer_id: Optional lecturer user ID (admin only). If specified, uses the lecturer's project.
                    Takes precedence over project_id.
        project_id: Optional project ID. If not specified, uses the user's own project.
                   Admins can specify any project ID to view other users' quotas.
        force_refresh: If True, bypasses cache and fetches fresh data from OpenStack
    
    Returns:
        QuotaResponse with quota limits, usage, and available resources
    """
    user_id = user.get("user_id")
    if not user_id:
        raise ForbiddenException("User ID not found in authentication token")
    
    user_roles = user.get("roles", [])
    is_admin = UserRole.ADMIN.value in user_roles
    
    # Determine target user and project
    target_user_id: str = user_id
    project_id_str = None
    
    # Priority: lecturer_id > project_id > user's project
    if lecturer_id:
        # Only admins can specify lecturer_id
        if not is_admin:
            raise ForbiddenException("Only admins can specify lecturer_id")
        
        target_user_id = str(lecturer_id)
        project_repo = OpenstackProjectRepository(db)
        
        # Step 1: Check if lecturer (user) exists in database
        if not project_repo.user_exists(target_user_id):
            logger.warning(f"Lecturer not found: {lecturer_id}")
            raise NotFoundException(f"Lecturer with ID {lecturer_id} does not exist")
        
        # Step 2: Check if lecturer has an OpenStack project
        lecturer_projects = project_repo.get_by_owner(target_user_id)
        if not lecturer_projects:
            logger.warning(f"No project found for lecturer: {lecturer_id}")
            raise NotFoundException(f"No OpenStack project found for lecturer with ID {lecturer_id}")
        
        # Each lecturer should have exactly one project, but handle edge case if multiple exist
        if len(lecturer_projects) > 1:
            logger.warning(
                f"Lecturer {lecturer_id} has {len(lecturer_projects)} projects (expected 1), using first one",
                extra={"lecturer_id": lecturer_id, "project_count": len(lecturer_projects)}
            )
        project_id_str = str(lecturer_projects[0].id)
    elif project_id:
        # Convert project_id to string if provided
        project_id_str = str(project_id)
        # Ownership check is handled by resource_service.get_quotas() via _get_project_for_user()
    
    # Get quotas
    resource_service = OpenstackResourceService(db)
    quotas_data = resource_service.get_quotas(
        user_id=target_user_id,
        project_id=project_id_str,
        use_cache=True,
        force_refresh=force_refresh,
        allow_admin_access=is_admin,  # Allow admins to access any project
    )
    
    # Include owner_user_id for admin access
    owner_user_id = quotas_data.get("owner_user_id") if is_admin else None
    
    # Convert to response schema
    response_data = QuotaResponse.from_service_dict(quotas_data, owner_user_id=owner_user_id)
    
    return ResponseBuilder.success(
        data=response_data,
        message="Quotas retrieved successfully",
        request_id=request_id,
    )
