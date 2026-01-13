"""Template API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, status, Query

from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination
from src.schemas.template import TemplateCreate, TemplateUpdate, TemplateResponse
from src.services.template_service import TemplateService


router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=None)
async def list_templates(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    status_filter: Optional[str] = Query(None, description="Filter by approval status (pending/approved/rejected/deprecated)", alias="status"),
    visibility: Optional[str] = Query(None, description="Filter by visibility (private/public)"),
    owner_id: Optional[str] = Query(None, description="Filter by owner ID"),
    search: Optional[str] = Query(None, description="Search in name and description"),
):
    """List all templates with optional filters and pagination.
    
    Supports filtering by:
    - Approval status (pending, approved, rejected, deprecated)
    - Visibility (private, public)
    - Owner ID
    - Search term (searches name and description)
    
    Returns paginated results with total count.
    """
    service = TemplateService(db)
    
    templates, total = service.list_templates(
        skip=(pagination.page - 1) * pagination.page_size,
        limit=pagination.page_size,
        status=status_filter,
        visibility=visibility,
        owner_id=owner_id,
        search=search,
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
):
    """Get a single template by ID.
    
    Returns complete template details including metadata and timestamps.
    """
    service = TemplateService(db)
    template = service.get_template(str(template_id))
    
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
):
    """Create a new template.
    
    Templates are created with initial approval status 'pending'.
    They must be approved by an admin before becoming publicly available.
    
    Note: Authentication integration pending. Currently uses mock owner_id.
    """
    service = TemplateService(db)
    
    # TODO: Replace with actual user ID from authentication token
    # For now, using a mock user ID for testing
    mock_owner_id = "00000000-0000-0000-0000-000000000000"
    
    template = service.create_template(template_data, owner_id=mock_owner_id)
    
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
):
    """Update an existing template.
    
    Only template owners or admins can update templates.
    Partial updates are supported - only provided fields will be updated.
    
    Note: Authentication and authorization integration pending.
    """
    service = TemplateService(db)
    
    # TODO: Replace with actual user ID and admin status from authentication
    # For now, using mock values for testing
    mock_user_id = "00000000-0000-0000-0000-000000000000"
    mock_is_admin = True
    
    template = service.update_template(
        template_id=str(template_id),
        template_data=template_data,
        user_id=mock_user_id,
        is_admin=mock_is_admin,
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
):
    """Delete a template.
    
    Only template owners or admins can delete templates.
    This is a permanent operation and cannot be undone.
    
    Note: Authentication and authorization integration pending.
    """
    service = TemplateService(db)
    
    # TODO: Replace with actual user ID and admin status from authentication
    # For now, using mock values for testing
    mock_user_id = "00000000-0000-0000-0000-000000000000"
    mock_is_admin = True
    
    service.delete_template(
        template_id=str(template_id),
        user_id=mock_user_id,
        is_admin=mock_is_admin,
    )
    
    # For 204 No Content, return None (FastAPI handles this correctly)
    return None
