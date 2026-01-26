"""Template Version File API routes."""
from uuid import UUID
from fastapi import APIRouter, status, Depends
from typing import Optional

from src.core.dependencies import DBSession, RequestID, require_roles, CurrentUser
from src.core.response_builder import ResponseBuilder
from src.schemas.template_version_file import (
    TemplateVersionFileCreate,
    TemplateVersionFileUpdate,
    TemplateVersionFileResponse,
    TemplateVersionFileListResponse
)
from src.services.template_version_file_service import TemplateVersionFileService
from src.models.user import UserRole

router = APIRouter(
    prefix="/template-version-files",
    tags=["template-version-files"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],  # All endpoints require at least LECTURER role
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=dict
)
async def create_file(
    file_data: TemplateVersionFileCreate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Create a new template version file.
    
    Args:
        file_data: File creation data
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
        
    Returns:
        Created file response
    """
    service = TemplateVersionFileService(db)
    file = service.create_file(file_data)
    
    return ResponseBuilder.created(
        data=TemplateVersionFileResponse.model_validate(file),
        message="Template version file created successfully",
        request_id=request_id
    )


@router.get(
    "/{file_id}",
    response_model=dict
)
async def get_file(
    file_id: str,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    include_content: bool = True
):
    """Get a template version file by ID.
    
    Args:
        file_id: File ID
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
        include_content: Whether to include file content
        
    Returns:
        File response
    """
    service = TemplateVersionFileService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    file = service.get_file(
        file_id,
        include_content=include_content,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    response_schema = TemplateVersionFileResponse if include_content else TemplateVersionFileListResponse
    
    return ResponseBuilder.success(
        data=response_schema.model_validate(file),
        message="File retrieved successfully",
        request_id=request_id
    )


@router.get(
    "/{file_id}/content",
    response_model=dict
)
async def get_file_content(
    file_id: str,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Get only the content of a template version file.
    
    Args:
        file_id: File ID
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
        
    Returns:
        File content
    """
    service = TemplateVersionFileService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    content = service.get_file_content(
        file_id,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    return ResponseBuilder.success(
        data={"content": content},
        message="File content retrieved successfully",
        request_id=request_id
    )


@router.get(
    "/version/{version_id}",
    response_model=dict
)
async def list_version_files(
    version_id: str,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    include_content: bool = False,
    file_type: Optional[str] = None
):
    """List all files for a template version.
    
    Args:
        version_id: Template version ID
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
        include_content: Whether to include file content
        file_type: Optional filter by file type
        
    Returns:
        List of files
    """
    service = TemplateVersionFileService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    files = service.get_version_files(
        version_id,
        include_content=include_content,
        file_type=file_type,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    response_schema = TemplateVersionFileResponse if include_content else TemplateVersionFileListResponse
    file_responses = [response_schema.model_validate(f) for f in files]
    
    return ResponseBuilder.success(
        data=file_responses,
        message=f"Retrieved {len(files)} file(s) for version {version_id}",
        request_id=request_id
    )


@router.get(
    "/version/{version_id}/primary",
    response_model=dict
)
async def get_primary_file(
    version_id: str,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Get the primary deployment file for a template version.
    
    Args:
        version_id: Template version ID
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
        
    Returns:
        Primary file or error if not found
    """
    service = TemplateVersionFileService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    file = service.get_primary_file(
        version_id,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    if not file:
        return ResponseBuilder.success(
            data=None,
            message=f"No primary file set for version {version_id}",
            request_id=request_id
        )
    
    return ResponseBuilder.success(
        data=TemplateVersionFileResponse.model_validate(file),
        message="Primary file retrieved successfully",
        request_id=request_id
    )


@router.get(
    "/version/{version_id}/parameters",
    response_model=dict
)
async def get_version_parameters(
    version_id: str,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Get Heat template parameters for a template version.
    
    Extracts and returns all parameters defined in the template version's app.yaml file.
    These parameters must be provided by the user when creating a deployment.
    
    Returns parameter definitions including:
    - name: Parameter name (e.g., 'instance_name', 'flavor')
    - type: Parameter type (string, int, number, boolean)
    - required: Whether parameter is mandatory
    - default: Default value if not required
    - description: Human-readable description for UI
    
    Use this endpoint to build deployment forms in the frontend.
    
    Args:
        version_id: Template version ID
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
        
    Returns:
        Template parameters response with list of parameter definitions
    """
    service = TemplateVersionFileService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    parameters_response = service.get_template_parameters(
        version_id,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    return ResponseBuilder.success(
        data=parameters_response.model_dump(mode="json"),
        message=f"Retrieved {len(parameters_response.parameters)} template parameters",
        request_id=request_id,
    )


@router.patch(
    "/{file_id}",
    response_model=dict
)
async def update_file(
    file_id: str,
    file_data: TemplateVersionFileUpdate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Update a template version file.
    
    Args:
        file_id: File ID
        file_data: Update data
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
        
    Returns:
        Updated file response
    """
    service = TemplateVersionFileService(db)
    file = service.update_file(file_id, file_data)
    
    return ResponseBuilder.success(
        data=TemplateVersionFileResponse.model_validate(file),
        message="File updated successfully",
        request_id=request_id
    )


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_file(
    file_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Delete a template version file.
    
    Args:
        file_id: File ID
        db: Database session
        request_id: Request ID for tracking
        current_user: Current authenticated user
    """
    service = TemplateVersionFileService(db)
    service.delete_file(file_id)
    
    # Return None for 204 No Content
    return None
