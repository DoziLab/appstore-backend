"""Template API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, status, Query, Depends

from src.core.response_builder import ResponseBuilder
from src.core.dependencies import DBSession, RequestID, Pagination, require_roles, CurrentUser
from src.schemas.template import (
    TemplateCreate,
    TemplateUpdate,
    TemplateResponse,
    GithubImportNewTemplate,
    GithubImportNewVersion,
)
from src.schemas.template_version import TemplateVersionResponse
from src.services.template_service import TemplateService
from src.services.github_import_service import GithubImportService
from src.models.user import UserRole
from src.models.template import TemplateVisibility


router = APIRouter(
    prefix="/templates",
    tags=["templates"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],  # All endpoints require at least LECTURER role
)


@router.get("", response_model=None)
async def list_templates(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
    visibility: Optional[str] = Query(None, description="Filter by visibility (private/public)"),
    owner_id: Optional[str] = Query(None, description="Filter by owner ID"),
    search: Optional[str] = Query(None, description="Search in name and description"),
):
    """List all templates with optional filters and pagination.

    Admins see all templates. Lecturers see their own templates plus public
    templates that have at least one APPROVED version (safety net — public
    templates whose versions are all still pending/rejected stay hidden from
    non-owners). Per-version approval gating is then enforced when the user
    fetches a specific TemplateVersion.

    Supports filtering by:
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
    current_user: CurrentUser,
):
    """Get a single template by ID.

    Admins can view any template. Lecturers can view their own templates plus
    public templates with at least one APPROVED version. Per-version approval
    is then enforced when fetching a specific TemplateVersion.
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
    current_user: CurrentUser,
):
    """Create a new template.

    Templates are created with visibility 'private'. Approval gating lives on
    each TemplateVersion (see /template-versions endpoints).

    Requires authentication. The authenticated user becomes the template owner.
    """
    service = TemplateService(db)

    template = service.create_template(template_data, owner_id=current_user["user_id"])

    template_response = TemplateResponse.model_validate(template)

    return ResponseBuilder.created(
        data=template_response.model_dump(mode="json"),
        message="Template created successfully",
        request_id=request_id,
    )


@router.patch("/{template_id}", response_model=None)
async def update_template(
    template_id: UUID,
    template_data: TemplateUpdate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
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
    current_user: CurrentUser,
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


@router.post(
    "/import-from-github",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def import_template_from_github(
    payload: GithubImportNewTemplate,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Create a new template plus its first version from a GitHub repository.

    Sichtbarkeitsregel:
    - ``visibility=private`` (Default) → Template ist sofort owner-only nutzbar,
      kein Approval-Flow.
    - ``visibility=public`` → Template wird ALS PRIVATE + ``publish_requested=True``
      persistiert; die erste Version geht durch den Admin-Approval-Flow. Erst
      beim ersten approve_version() flippt das Template atomar auf PUBLIC.
      So sieht der Owner sofort „wartet auf Erst-Freigabe" statt eines
      fälschlich-öffentlichen Templates ohne approved Version. Admin-Caller
      umgehen den Flow (Auto-Approval + Direkt-Promotion).

    Für private Repos muss der Caller unsere GitHub App via
    ``POST /auth/github/install`` verbunden haben. Public Repos funktionieren
    auch ohne Installation (GitHub-API 60/h-Rate-Limit).
    """
    service = GithubImportService(db)
    template = service.import_to_new_template(
        github_url=payload.github_url,
        app_yaml_path=payload.app_yaml_path,
        name=payload.name,
        description=payload.description,
        icon_url=payload.icon_url,
        owner_user_id=current_user["user_id"],
        owner_user_roles=current_user.get("roles", []),
        # The pydantic validator normalises this to "private"/"public" (or
        # leaves the default). Map the string to the enum here so the service
        # stays typed.
        visibility=TemplateVisibility(payload.visibility or "private"),
    )

    template_response = TemplateResponse.model_validate(template)
    return ResponseBuilder.created(
        data=template_response.model_dump(mode="json"),
        message="Template imported from GitHub successfully",
        request_id=request_id,
    )


@router.post(
    "/{template_id}/import-from-github",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def import_new_version_from_github(
    template_id: UUID,
    payload: GithubImportNewVersion,
    db: DBSession,
    request_id: RequestID,
    current_user: CurrentUser,
):
    """Append a new version to an existing template, populated from GitHub.

    Owner-or-admin only. For private repos the calling user must have linked
    our GitHub App via `POST /auth/github/install`. Approval defaults to
    PENDING unless the user is an admin and the parent template is public,
    in which case the new version is auto-approved.
    """
    service = GithubImportService(db)
    version = service.import_to_existing_template(
        template_id=str(template_id),
        github_url=payload.github_url,
        app_yaml_path=payload.app_yaml_path,
        is_active=payload.is_active,
        user_id=current_user["user_id"],
        user_roles=current_user.get("roles", []),
        replace_existing=payload.replace_existing,
    )

    version_response = TemplateVersionResponse.model_validate(version)
    return ResponseBuilder.created(
        data=version_response.model_dump(mode="json"),
        message="Template version imported from GitHub successfully",
        request_id=request_id,
    )
