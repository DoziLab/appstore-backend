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
    status_filter: DeploymentStatus | None = Query(None, description="Filter by status", alias="status"),
):
    """List deployments with optional filters."""
    
    return ResponseBuilder.paginated(
        data=[],
        page=pagination.page,
        page_size=pagination.page_size,
        total=0,
        message="Deployments retrieved successfully",
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
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")
    
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
    request_id: RequestID
):
    """Get OpenStack Heat stack information for a deployment.
    
    Returns current stack status, resources, and outputs.
    
    Args:
        deployment_id: ID of the deployment
        db: Database session
        request_id: Request ID for tracing
        
    Returns:
        Stack information including status and resources
        
    Raises:
        NotFoundException: If deployment does not exist
        HTTPException: If stack information cannot be retrieved
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")
    
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
