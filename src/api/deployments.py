"""Deployment API endpoints."""
from uuid import UUID
from fastapi import APIRouter, status, Query
from src.models.deployment import DeploymentStatus
from src.models.user import UserRole
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination, CurrentUser, require_roles
from src.schemas.deployment import DeploymentResponse, DeploymentCreate
from src.services.deployment_service import DeploymentService


router = APIRouter(prefix="/deployments", tags=["deployments"])

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
    user: CurrentUser = require_roles(UserRole.ADMIN, UserRole.LECTURER),
) -> dict:
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
    deployment = service.create_deployment(deployment_data)
    
    # Convert SQLAlchemy model to response schema
    deployment_response = DeploymentResponse.model_validate(deployment)
    
    return ResponseBuilder.created(
        data=deployment_response.model_dump(mode="json"),
        message="Deployment created and queued for processing",
        request_id=request_id,
    )