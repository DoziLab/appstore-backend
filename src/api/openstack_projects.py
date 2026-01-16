"""OpenStack Projects API endpoints."""
from uuid import UUID, uuid4
from fastapi import APIRouter, status, Depends
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, require_roles
from src.models.user import UserRole
from src.schemas.openstack_project import (
    OpenstackCredentialsCreate,
    OpenstackCredentialsResponse,
    OpenstackProjectResponse,
)
from src.services.openstack_project_service import OpenstackProjectService
from src.core.auth import get_user_id


router = APIRouter(
    prefix="/openstack-projects",
    tags=["openstack-projects"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],  # All endpoints require at least LECTURER role
)


@router.get("", response_model=list[OpenstackProjectResponse])
async def list_openstack_projects(
    db: DBSession,
    request_id: RequestID,
    user_id: str = Depends(get_user_id),
):
    """List all OpenStack projects for the current user.
    
    Returns basic project information without credentials.
    """
    service = OpenstackProjectService(db)
    
    projects = service.list_projects_for_user(user_id, request_id)
    
    # Convert to response schema without credentials
    response_data = [
        OpenstackProjectResponse(
            id=p.id,
            owner_user_id=p.owner_user_id,
            openstack_project_id=p.openstack_project_id,
            openstack_project_name=p.openstack_project_name,
            region_name=p.region_name,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in projects
    ]
    
    return ResponseBuilder.success(
        data=response_data,
        message="OpenStack projects retrieved successfully",
        request_id=request_id,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OpenstackCredentialsResponse,
)
async def create_project(
    credentials: OpenstackCredentialsCreate,
    db: DBSession,
    request_id: RequestID,
    user_id: str = Depends(get_user_id),
):
    """Create a new OpenStack project with credentials.
    
    Generates a new UUID for the project.
    Credentials are automatically encrypted using Fernet symmetric encryption.
    
    IMPORTANT: Never log the credentials object or response.
    """
    service = OpenstackProjectService(db)
    
    # Generate new project UUID
    project_id = str(uuid4())
    
    project = service.create_credentials(
        project_id=project_id,
        credentials=credentials,
        owner_user_id=user_id,
        request_id=request_id,
    )
    
    # Return masked credentials
    response_data = OpenstackCredentialsResponse.from_orm_masked(project)
    
    return ResponseBuilder.created(
        data=response_data,
        message="OpenStack project created successfully",
        request_id=request_id,
    )


@router.put(
    "/{project_id}",
    response_model=OpenstackCredentialsResponse,
)
async def update_project_credentials(
    project_id: str,
    credentials: OpenstackCredentialsCreate,
    db: DBSession,
    request_id: RequestID,
    user_id: str = Depends(get_user_id),
):
    """Update OpenStack credentials for an existing project.
    
    Credentials are automatically encrypted using Fernet symmetric encryption.
    Only the project owner can update credentials.
    
    IMPORTANT: Never log the credentials object or response.
    """
    service = OpenstackProjectService(db)
    
    project = service.update_credentials(
        project_id=project_id,
        credentials=credentials,
        owner_user_id=user_id,
        request_id=request_id,
    )
    
    # Return masked credentials
    response_data = OpenstackCredentialsResponse.from_orm_masked(project)
    
    return ResponseBuilder.success(
        data=response_data,
        message="OpenStack credentials updated successfully",
        request_id=request_id,
    )


@router.get(
    "/{project_id}",
    response_model=OpenstackCredentialsResponse,
)
async def get_project_credentials(
    project_id: UUID,
    db: DBSession,
    request_id: RequestID,
    user_id: str = Depends(get_user_id),
):
    """Get OpenStack project with credentials (masked).
    
    Returns credentials with masked password and partially masked username.
    Access is logged for audit purposes.
    Only the project owner can retrieve credentials.
    """
    service = OpenstackProjectService(db)
    
    project = service.get_credentials(
        project_id=project_id,
        user_id=user_id,
        request_id=request_id,
    )
    
    # Return masked credentials
    response_data = OpenstackCredentialsResponse.from_orm_masked(project)
    
    return ResponseBuilder.success(
        data=response_data,
        message="OpenStack project retrieved successfully",
        request_id=request_id,
    )


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project(
    project_id: UUID,
    db: DBSession,
    request_id: RequestID,
    user_id: str = Depends(get_user_id),
):
    """Delete OpenStack project and its credentials.
    
    Removes the entire project and its encrypted credentials.
    Only the project owner can delete the project.
    Deletion is logged for audit purposes.
    """
    service = OpenstackProjectService(db)
    
    service.delete_credentials(
        project_id=project_id,
        user_id=user_id,
        request_id=request_id,
    )
    
    return ResponseBuilder.success(
        data=None,
        message="OpenStack project deleted successfully",
        request_id=request_id,
    )
