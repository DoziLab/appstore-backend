"""Deployment API endpoints."""
from uuid import UUID
from fastapi import APIRouter, status, Query
from src.models.deployment import DeploymentStatus
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination
from src.schemas.deployment import DeploymentResponse, DeploymentCreate
from src.services.deployment_service import DeploymentService


router = APIRouter(prefix="/deployments", tags=["deployments"])

@router.get("")
async def list_deployments(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
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
def create_deployment(
    deployment_data: DeploymentCreate,
    db: DBSession,
    request_id: RequestID
):
    service = DeploymentService(db)
    deployment = service.create_deployment(deployment_data)
    
    # Convert SQLAlchemy model to response schema
    deployment_response = DeploymentResponse.model_validate(deployment)
    
    return ResponseBuilder.created(
        data=deployment_response.model_dump(mode="json"),
        message="Deployment created and queued for processing",
        request_id=request_id,
    )