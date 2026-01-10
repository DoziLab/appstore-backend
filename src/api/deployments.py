"""Deployment API endpoints."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from src.models.deployment import DeploymentStatus
from src.models.user import UserRole
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination, require_role, CurrentUser
from src.schemas.deployment import DeploymentResponse, DeploymentCreate
from src.services.deployment_service import DeploymentService


router = APIRouter(prefix="/deployments", tags=["deployments"])


@router.get("")
async def list_deployments(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    course_id: UUID | None = Query(None, description="Filter by course ID"),
    status_filter: DeploymentStatus | None = Query(None, description="Filter by status", alias="status"),
):
    """List deployments with optional filters.
    
    Requires authentication. Returns deployments filtered by course_id and/or status.
    """
    service = DeploymentService(db)
    
    deployments, total = service.list_deployments(
        course_id=course_id,
        status=status_filter,
        skip=pagination.offset,
        limit=pagination.page_size
    )
    
    # Convert to response schema
    deployment_responses = [DeploymentResponse.model_validate(d) for d in deployments]
    
    return ResponseBuilder.paginated(
        data=[d.model_dump(mode="json") for d in deployment_responses],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        message="Deployments retrieved successfully",
        request_id=request_id,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_deployment(
    deployment_data: DeploymentCreate,
    db: DBSession,
    request_id: RequestID,
    current_user = Depends(require_role(UserRole.ADMIN, UserRole.LECTURER))
):
    """Create a new deployment (Admin and Lecturer only).
    
    Creates a deployment from a template reference and triggers async deployment processing.
    OpenStack parameters are optional and will use defaults if not provided.
    """
    service = DeploymentService(db)
    
    try:
        deployment = service.create_deployment(deployment_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    # Convert SQLAlchemy model to response schema
    deployment_response = DeploymentResponse.model_validate(deployment)
    
    return ResponseBuilder.created(
        data=deployment_response.model_dump(mode="json"),
        message="Deployment created and queued for processing",
        request_id=request_id,
    )


@router.get("/{deployment_id}")
async def get_deployment(
    deployment_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Get a specific deployment by ID.
    
    Requires authentication.
    """
    service = DeploymentService(db)
    deployment = service.get_deployment(deployment_id)
    
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment with ID {deployment_id} not found"
        )
    
    deployment_response = DeploymentResponse.model_validate(deployment)
    
    return ResponseBuilder.success(
        data=deployment_response.model_dump(mode="json"),
        message="Deployment retrieved successfully",
        request_id=request_id,
    )