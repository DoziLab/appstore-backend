"""Deployment API endpoints."""
from uuid import UUID
from fastapi import APIRouter, status, Query, Depends, HTTPException
from src.core.exceptions import NotFoundException
from src.models.deployment import DeploymentStatus
from src.models.user import UserRole
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination, CurrentUser, require_roles
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.schemas.deployment import DeploymentResponse, DeploymentCreate
from src.services.deployment_service import DeploymentService
from src.services.deployment_log_service import DeploymentLogService
from src.services.openstack_heat_service import HeatStackService
from src.schemas.deployment import DeploymentLogResponse
from src.tasks.deploy_tasks import delete_deployment as delete_deployment_task
from src.models.deployment_log import DeploymentLogEventType, DeploymentLogLevel

router = APIRouter(
    prefix="/deployments",
    tags=["deployments"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],  # All endpoints require at least LECTURER role
)

@router.get("")
async def list_deployments(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    course_id: UUID | None = Query(None, description="Filter by course ID"),
    template_id: UUID | None = Query(None, description="Filter by template ID"),
    status_filter: str | None = Query(None, description="Filter by OpenStack stack status (e.g., CREATE_COMPLETE, DELETE_COMPLETE)", alias="status"),
):
    """List all OpenStack Heat stacks for the current user.
    
    Fetches stacks directly from OpenStack API and enriches them with deployment
    information from the database if available. This ensures the list always shows
    what actually exists in OpenStack, not just what's tracked in the database.
    
    Returns stack information including:
    - Current stack status from OpenStack
    - Stack resources (VMs, networks, etc.)
    - Stack outputs (access URLs, IPs, etc.)
    - Associated deployment information (if tracked in database)
    
    Optional filters:
    - Course ID: Only show stacks associated with a specific course
    - Template ID: Only show stacks associated with a specific template
    - Status: Filter by OpenStack stack status (e.g., CREATE_COMPLETE, DELETE_COMPLETE)
    
    Returns paginated results with total count.
    """
    service = DeploymentService(db)
    
    # Check if user is admin
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    
    # Fetch stacks: admins get all (user_id=None), lecturers get only their own
    all_stacks = service.list_all_openstack_stacks(user_id=None if is_admin else user["user_id"])
    
    # Apply filters
    filtered_stacks = all_stacks
    
    if course_id:
        filtered_stacks = [
            s for s in filtered_stacks 
            if s.get('course_id') == str(course_id)
        ]
    
    if template_id:
        # Filter by template_id (requires deployment_id to fetch from DB)
        deployment_ids = [s.get('deployment_id') for s in filtered_stacks if s.get('deployment_id')]
        if deployment_ids:
            # Fetch deployments from DB to check template_version_id -> template_id relationship
            matching_deployment_ids = set()
            
            for deployment_id in deployment_ids:
                if deployment_id is None:
                    continue
                deployment = service.deployment_repo.get_by_id(deployment_id)
                if deployment and deployment.template_version:
                    if deployment.template_version.template_id == template_id:
                        matching_deployment_ids.add(str(deployment.id))
            
            filtered_stacks = [
                s for s in filtered_stacks 
                if s.get('deployment_id') in matching_deployment_ids
            ]
        else:
            # No deployments with deployment_id, so template_id filter results in empty list
            filtered_stacks = []
    
    if status_filter:
        # Filter by OpenStack stack status (case-insensitive)
        filtered_stacks = [
            s for s in filtered_stacks 
            if s.get('status', '').upper() == status_filter.upper()
        ]
    
    # Apply pagination
    total = len(filtered_stacks)
    start_idx = (pagination.page - 1) * pagination.page_size
    end_idx = start_idx + pagination.page_size
    paginated_stacks = filtered_stacks[start_idx:end_idx]
    
    return ResponseBuilder.paginated(
        data=paginated_stacks,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        message=f"Retrieved {len(paginated_stacks)} stacks from OpenStack (total: {total})",
        request_id=request_id,
    )

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_deployment(
    deployment_data: DeploymentCreate,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """Create a new deployment (One-Click Deployment).
    
    Initiates deployment of a template version to a course.
    The deployment is queued and processed asynchronously via Celery.
    
    **Authorization:** Requires ADMIN or LECTURER role.
    
    Args:
        deployment_data: Deployment creation request with template_id, course_id, target_type
        db: Database session
        request_id: Request correlation ID
        user: Authenticated user with required role (auto-validated)
        
    Returns:
        Created deployment with status QUEUED
    """
    service = DeploymentService(db)
    deployment = service.create_deployment(deployment_data, request_id=request_id)
    
    # Convert SQLAlchemy model to response schema
    deployment_response = DeploymentResponse.model_validate(deployment)
    
    return ResponseBuilder.created(
        data=deployment_response.model_dump(mode="json"),
        message="Deployment created and queued for processing",
        request_id=request_id,
    )

@router.get("/{deployment_id}/logs", response_model=dict)
async def get_deployment_logs(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """
    Get all logs for a specific deployment.
    
    Returns logs in chronological order (oldest first).
    
    Args:
        deployment_id: ID of the deployment
        db: Database session
        request_id: Request ID for tracing
        
    Returns:
        List of deployment log entries
        
    Raises:
        NotFoundException: If deployment does not exist
        HTTPException: If access is forbidden
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")
    
    # Check authorization: Lecturers can only see their own deployments
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    
    if not is_admin:
        # Non-admin users can only access their own deployments
        lecturer_id = deployment.course.lecturer_id
        if user["user_id"] != lecturer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this deployment"
            )
    
    # Get logs
    log_service = DeploymentLogService(db)
    logs = log_service.get_deployment_logs(deployment_id)
    
    return ResponseBuilder.success(
        data=[DeploymentLogResponse.model_validate(log) for log in logs],
        message=f"Retrieved {len(logs)} log entries for deployment",
        request_id=request_id
    )


@router.get("/{deployment_id}/stack")
async def get_deployment_stack(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
):
    """Get OpenStack Heat stack information for a deployment.
    
    Returns current stack status, resources, and outputs.
    
    Args:
        deployment_id: ID of the deployment
        db: Database session
        request_id: Request ID for tracing
        user: Authenticated user
        
    Returns:
        Stack information including status and resources
        
    Raises:
        NotFoundException: If deployment does not exist
        HTTPException: If stack information cannot be retrieved or access is forbidden
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")
    
    # Check authorization: Lecturers can only see their own deployments
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    
    if not is_admin:
        # Non-admin users can only access their own deployments
        lecturer_id = deployment.course.lecturer_id
        if user["user_id"] != lecturer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this deployment"
            )
    
    if not deployment.openstack_stack_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Heat stack associated with this deployment"
        )
    
    # Get lecturer's OpenStack project
    openstack_repo = OpenstackProjectRepository(db)
    lecturer_id = deployment.course.lecturer_id
    openstack_projects = openstack_repo.get_by_owner(lecturer_id)
    
    if not openstack_projects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No OpenStack project found for lecturer {lecturer_id}"
        )
    
    openstack_project = openstack_projects[0]
    
    try:
        heat_service = HeatStackService(openstack_project)
        
        # Get stack details
        stack_info = heat_service.get_stack(deployment.openstack_stack_id)
        
        # Get stack resources
        try:
            resources = heat_service.get_stack_resources(deployment.openstack_stack_id)
        except Exception:
            resources = []
        
        # Get stack outputs
        try:
            outputs = heat_service.get_stack_outputs(deployment.openstack_stack_id)
        except Exception:
            outputs = {}
        
        return ResponseBuilder.success(
            data={
                "stack": stack_info,
                "resources": resources,
                "outputs": outputs
            },
            message="Stack information retrieved successfully",
            request_id=request_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve stack information: {str(e)}"
        )


@router.delete(
    "/{deployment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a deployment",
    responses={
        204: {"description": "Deletion requested; operation in progress"},
        403: {"description": "Forbidden - not owner or insufficient role"},
        404: {"description": "Deployment not found"},
        500: {"description": "Failed to enqueue deletion task or internal error"},
    },
)
async def delete_deployment(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """Request deletion of a deployment.

    Sets deployment status to DELETING, logs the request and enqueues the
    `delete_deployment` Celery task which performs the actual OpenStack
    deletion and cleans up the database.
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    # Authorization: Lecturers may delete only their own deployments
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]

    if not is_admin:
        lecturer_id = deployment.course.lecturer_id
        if user["user_id"] != lecturer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this deployment",
            )

    # Set status to DELETING in DB
    try:
        deployment_repo.update_status(deployment_id, DeploymentStatus.DELETING)
    except Exception:
        # If status update fails, continue to enqueue task but log it
        pass

    # Write a deployment log entry
    log_service = DeploymentLogService(db)
    log_service.log(
        deployment_id=deployment_id,
        event_type=DeploymentLogEventType.DEPLOYMENT_DELETION_REQUESTED,
        message="Deletion requested via API",
        level=DeploymentLogLevel.INFO,
        details={"requested_by": user.get("user_id")},
        request_id=request_id,
    )

    # Enqueue Celery task to perform deletion asynchronously
    try:
        delete_deployment_task.delay(deployment_id)
    except Exception:
        # If queuing fails, attempt to revert status and return server error
        try:
            deployment_repo.update_status(deployment_id, DeploymentStatus.FAILED)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue deletion task",
        )

    return ResponseBuilder.no_content(
        message="Deletion requested; operation is in progress",
        request_id=request_id,
    )
