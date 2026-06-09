"""Template Version API endpoints."""
from uuid import UUID

from fastapi import APIRouter, status, Query, Depends

from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, require_roles, CurrentUser
from src.schemas.template_version import (
    TemplateVersionCreate,
    TemplateVersionUpdate,
    TemplateVersionResponse,
    TemplateVersionWithFilesResponse
)
from src.services.template_version_service import TemplateVersionService
from src.models.user import UserRole


router = APIRouter(
    prefix="/template-versions",
    tags=["template-versions"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],  # All endpoints require at least LECTURER role
)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_version(
    version_data: TemplateVersionCreate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Create a new template version.
    
    Only template owners or admins can create versions.
    If set as active, automatically deactivates other versions of the same template.
    
    Requires authentication. Permission checks enforce ownership or admin role.
    """
    service = TemplateVersionService(db)
    
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    version = service.create_version(
        version_data,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    version_response = TemplateVersionResponse.model_validate(version)
    
    return ResponseBuilder.created(
        data=version_response.model_dump(mode="json"),
        message="Template version created successfully",
        request_id=request_id,
    )


@router.get("/{version_id}", response_model=None)
async def get_version(
    version_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    with_file_count: bool = Query(False, description="Include file count in response"),
    include_parameters: bool = Query(True, description="Include parameters from app.yaml"),
):
    """Get a single template version by ID.
    
    Optionally includes the count of files associated with this version.
    By default, includes parameters parsed from app.yaml manifest.
    Requires authentication. Access control checks parent template permissions.
    """
    service = TemplateVersionService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    if include_parameters:
        # Get version with parameters
        result_with_params = service.get_version_with_parameters(
            str(version_id),
            with_file_count=with_file_count,
            user_id=current_user["user_id"],
            is_admin=is_admin
        )
        version = result_with_params["version"]
        parameters = result_with_params.get("parameters", [])
        user_files = result_with_params.get("user_files", [])
        allow_user_files = result_with_params.get("allow_user_files", False)

        if with_file_count:
            version_data = TemplateVersionWithFilesResponse.model_validate(version).model_dump(mode="json")
            version_data["file_count"] = result_with_params["file_count"]
            version_data["parameters"] = parameters
            version_data["user_files"] = user_files
            version_data["allow_user_files"] = allow_user_files
        else:
            version_data = TemplateVersionResponse.model_validate(version).model_dump(mode="json")
            version_data["parameters"] = parameters
            version_data["user_files"] = user_files
            version_data["allow_user_files"] = allow_user_files
        
        return ResponseBuilder.success(
            data=version_data,
            message="Template version retrieved successfully",
            request_id=request_id,
        )
    else:
        # Original behavior without parameters
        result_with_no_params = service.get_version(
            str(version_id),
            with_file_count=with_file_count,
            user_id=current_user["user_id"],
            is_admin=is_admin
        )
        if with_file_count:
            if not isinstance(result_with_no_params, dict):
                raise ValueError("Expected dict result when with_file_count=True")
            version = result_with_no_params["version"]
            version_data = TemplateVersionWithFilesResponse.model_validate(version).model_dump(mode="json")
            version_data["file_count"] = result_with_no_params["file_count"]
            return ResponseBuilder.success(
                data=version_data,
                message="Template version retrieved successfully",
                request_id=request_id,
            )
        else:
            version_response = TemplateVersionResponse.model_validate(result_with_no_params)
            return ResponseBuilder.success(
                data=version_response.model_dump(mode="json"),
                message="Template version retrieved successfully",
                request_id=request_id,
            )


@router.get("/template/{template_id}", response_model=None)
async def list_template_versions(
    template_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    active_only: bool = Query(False, description="Return only active versions"),
    include_parameters: bool = Query(False, description="Include parameters from app.yaml for each version"),
):
    """List all versions for a specific template.
    
    Returns versions ordered by creation date (newest first).
    Can be filtered to show only active versions.
    Optionally includes parameters parsed from app.yaml for each version.
    Requires authentication. Access control checks parent template permissions.
    """
    service = TemplateVersionService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    versions = service.list_template_versions(
        str(template_id),
        active_only=active_only,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    if include_parameters:
        # Include parameters for each version
        version_responses = []
        for version in versions:
            result = service.get_version_with_parameters(
                str(version.id),
                user_id=current_user["user_id"],
                is_admin=is_admin
            )
            version_data = TemplateVersionResponse.model_validate(result["version"]).model_dump(mode="json")
            version_data["parameters"] = result.get("parameters", [])
            version_data["user_files"] = result.get("user_files", [])
            version_data["allow_user_files"] = result.get("allow_user_files", False)
            version_responses.append(version_data)
    else:
        version_responses = [
            TemplateVersionResponse.model_validate(version).model_dump(mode="json")
            for version in versions
        ]
    
    return ResponseBuilder.success(
        data=version_responses,
        message=f"Retrieved {len(versions)} version(s) for template",
        request_id=request_id,
    )


@router.get("/template/{template_id}/active", response_model=None)
async def get_active_version(
    template_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    include_parameters: bool = Query(True, description="Include parameters from app.yaml"),
):
    """Get the active version for a specific template.
    
    Returns the currently active version or 404 if no active version exists.
    By default, includes parameters parsed from app.yaml manifest.
    Requires authentication. Access control checks parent template permissions.
    """
    service = TemplateVersionService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    version = service.get_active_version(
        str(template_id),
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    if not version:
        return ResponseBuilder.success(
            data=None,
            message="No active version found for this template",
            request_id=request_id,
        )
    
    if include_parameters:
        # Get version with parameters
        result = service.get_version_with_parameters(
            str(version.id),
            user_id=current_user["user_id"],
            is_admin=is_admin
        )
        version_data = TemplateVersionResponse.model_validate(result["version"]).model_dump(mode="json")
        version_data["parameters"] = result.get("parameters", [])
        version_data["user_files"] = result.get("user_files", [])
        version_data["allow_user_files"] = result.get("allow_user_files", False)
        
        return ResponseBuilder.success(
            data=version_data,
            message="Active template version retrieved successfully",
            request_id=request_id,
        )
    else:
        version_response = TemplateVersionResponse.model_validate(version)
        
        return ResponseBuilder.success(
            data=version_response.model_dump(mode="json"),
            message="Active template version retrieved successfully",
            request_id=request_id,
        )


@router.patch("/{version_id}", response_model=None)
async def update_version(
    version_id: UUID,
    version_data: TemplateVersionUpdate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Update an existing template version.
    
    Only template owners or admins can update versions.
    If setting as active, automatically deactivates other versions.
    
    Requires authentication. Permission checks enforce ownership or admin role.
    """
    service = TemplateVersionService(db)
    
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    version = service.update_version(
        str(version_id),
        version_data,
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    version_response = TemplateVersionResponse.model_validate(version)
    
    return ResponseBuilder.success(
        data=version_response.model_dump(mode="json"),
        message="Template version updated successfully",
        request_id=request_id,
    )


@router.post("/{version_id}/activate", response_model=None)
async def activate_version(
    version_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Activate a specific template version.
    
    Automatically deactivates all other versions of the same template.
    Only template owners or admins can activate versions.
    
    Requires authentication. Permission checks enforce ownership or admin role.
    """
    service = TemplateVersionService(db)
    
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    version = service.activate_version(
        str(version_id),
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    version_response = TemplateVersionResponse.model_validate(version)
    
    return ResponseBuilder.success(
        data=version_response.model_dump(mode="json"),
        message="Template version activated successfully",
        request_id=request_id,
    )


@router.delete("/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(
    version_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Delete a template version.
    
    Only template owners or admins can delete versions.
    Cannot delete the only active version of a template.
    This operation cannot be undone.
    
    Requires authentication. Permission checks enforce ownership or admin role.
    """
    service = TemplateVersionService(db)
    
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    service.delete_version(
        str(version_id),
        user_id=current_user["user_id"],
        is_admin=is_admin
    )
    
    return None
