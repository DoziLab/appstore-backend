"""Template API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, status, Query, Depends

from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination, require_roles
from src.schemas.template import TemplateCreate, TemplateUpdate, TemplateResponse
from src.services.template_service import TemplateService
from src.models.user import UserRole


router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=None)
async def list_templates(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    current_user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
    status_filter: Optional[str] = Query(None, description="Filter by approval status (pending/approved/rejected/deprecated)", alias="status"),
    visibility: Optional[str] = Query(None, description="Filter by visibility (private/public)"),
    owner_id: Optional[str] = Query(None, description="Filter by owner ID"),
    search: Optional[str] = Query(None, description="Search in name and description"),
):
    """List all templates with optional filters and pagination.
    
    Admins see all templates. Lecturers see only approved public templates and their own templates.
    
    Supports filtering by:
    - Approval status (pending, approved, rejected, deprecated)
    - Visibility (private, public)
    - Owner ID
    - Search term (searches name and description)
    
    Returns paginated results with total count.
    """
    service = TemplateService(db)
    
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    templates, total = service.list_templates(
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
        status=status_filter,
        visibility=visibility,
        owner_id=owner_id,
        search=search,
        user_id=current_user["user_id"],
        is_admin=is_admin,
    )
    
    # Convert to response schemas
    template_responses = [
        TemplateResponse.model_validate(template).model_dump(mode="json")
        for template in templates
    ]
    
    return ResponseBuilder.paginated(
        data=template_responses,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        message="Templates retrieved successfully",
        request_id=request_id,
    )


@router.get("/{template_id}", response_model=None)
async def get_template(
    template_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
):
    """Get a single template by ID.
    
    Admins can view any template. Lecturers can only view approved public templates or their own templates.
    Returns complete template details including metadata and timestamps.
    """
    service = TemplateService(db)
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    template = service.get_template(str(template_id), user_id=current_user["user_id"], is_admin=is_admin)
    
    template_response = TemplateResponse.model_validate(template)
    
    return ResponseBuilder.success(
        data=template_response.model_dump(mode="json"),
        message="Template retrieved successfully",
        request_id=request_id,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_template(
    template_data: TemplateCreate,
    db: DBSession,
    request_id: RequestID,
    current_user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
):
    """Create a new template.
    
    Templates are created with visibility 'private' and approval status 'pending'.
    They must be approved by an admin before becoming publicly available.
    
    Requires authentication. The authenticated user becomes the template owner.
    """
    service = TemplateService(db)
    
    template = service.create_template(template_data, owner_id=current_user["user_id"])
    
    template_response = TemplateResponse.model_validate(template)
    
    return ResponseBuilder.created(
        data=template_response.model_dump(mode="json"),
        message="Template created successfully with status 'pending'",
        request_id=request_id,
    )


@router.patch("/{template_id}", response_model=None)
async def update_template(
    template_id: UUID,
    template_data: TemplateUpdate,
    db: DBSession,
    request_id: RequestID,
    current_user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
):
    """Update an existing template.
    
    Only template owners or admins can update templates.
    Only admins can change visibility.
    Partial updates are supported - only provided fields will be updated.
    
    Requires authentication. Permission checks enforce ownership or admin role.
    """
    service = TemplateService(db)
    
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    template = service.update_template(
        template_id=str(template_id),
        template_data=template_data,
        user_id=current_user["user_id"],
        is_admin=is_admin,
    )
    
    template_response = TemplateResponse.model_validate(template)
    
    return ResponseBuilder.success(
        data=template_response.model_dump(mode="json"),
        message="Template updated successfully",
        request_id=request_id,
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
):
    """Delete a template.
    
    Only template owners or admins can delete templates.
    This is a permanent operation and cannot be undone.
    
    Requires authentication. Permission checks enforce ownership or admin role.
    """
    service = TemplateService(db)
    
    is_admin = UserRole.ADMIN.value in current_user.get("roles", [])
    
    service.delete_template(
        template_id=str(template_id),
        user_id=current_user["user_id"],
        is_admin=is_admin,
    )
    
    # For 204 No Content, return None (FastAPI handles this correctly)
    return None


@router.post("/{template_id}/approve", response_model=None)
async def approve_template(
    template_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: dict = Depends(require_roles(UserRole.ADMIN)),
):
    """Approve a template for public use.
    
    Only admins can approve templates.
    Automatically sets visibility to 'public' and approval status to 'approved'.
    Approved templates become available to all lecturers.
    
    Requires authentication with admin role.
    """
    service = TemplateService(db)
    template = service.approve_template(str(template_id))
    
    template_response = TemplateResponse.model_validate(template)
    
    return ResponseBuilder.success(
        data=template_response.model_dump(mode="json"),
        message="Template approved successfully",
        request_id=request_id,
    )


@router.post("/{template_id}/reject", response_model=None)
async def reject_template(
    template_id: UUID,
    db: DBSession,
    request_id: RequestID,
    current_user: dict = Depends(require_roles(UserRole.ADMIN)),
):
    """Reject a template.
    
    Only admins can reject templates.
    Rejected templates remain visible to owners but are not publicly available.
    
    Requires authentication with admin role.
    """
    service = TemplateService(db)
    template = service.reject_template(str(template_id))
    
    template_response = TemplateResponse.model_validate(template)
    
    return ResponseBuilder.success(
        data=template_response.model_dump(mode="json"),
        message="Template rejected successfully",
        request_id=request_id,
    )
