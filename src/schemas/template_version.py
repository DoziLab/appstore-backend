"""Template Version schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, Any


class TemplateVersionCreate(BaseModel):
    """Schema for creating a template version."""
    template_id: str = Field(..., description="ID of the template")
    version: str = Field(..., description="Semantic version (e.g., 0.2.0)", max_length=50)
    git_commit_sha: str = Field(..., description="Git commit SHA for this version", max_length=255)
    is_active: bool = Field(default=True, description="Whether this version is active")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": "tmpl-123",
                "version": "0.2.0",
                "git_commit_sha": "a1b2c3d4e5f6g7h8i9j0",
                "is_active": True
            }
        }
    )


class TemplateVersionUpdate(BaseModel):
    """Schema for updating a template version."""
    git_commit_sha: Optional[str] = Field(None, description="Git commit SHA for this version", max_length=255)
    is_active: Optional[bool] = Field(None, description="Whether this version is active")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "is_active": False
            }
        }
    )


class TemplateVersionFileInline(BaseModel):
    """Inline file payload used by `POST /template-versions/with-files`."""
    file_name: str = Field(..., max_length=255)
    file_type: str = Field(..., description="FileType enum value")
    file_path: str = Field(..., max_length=500, description="Relative path within the template tree")
    content: str = Field(..., description="Full text content of the file")
    description: Optional[str] = None
    is_primary: bool = Field(default=False)
    order: int = Field(default=0)


class TemplateVersionWithFilesCreate(BaseModel):
    """Create a new TemplateVersion atomically together with all its files.

    Used for the "user edits in UI -> creates new version" flow.
    """
    template_id: str
    version: str = Field(..., max_length=50)
    git_commit_sha: str = Field(..., max_length=255)
    is_active: bool = Field(default=True)
    base_version_id: Optional[str] = Field(
        default=None,
        description="Optional version whose files are copied first; inline `files` overlay it by file_path",
    )
    files: list[TemplateVersionFileInline] = Field(
        default_factory=list,
        description="Files to attach to the new version. Must include exactly one APP_MANIFEST file_type unless base_version_id provides one.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template_id": "tmpl-123",
                "version": "1.2.0",
                "git_commit_sha": "manual-edit-2026-06-01T12:34:56Z",
                "is_active": True,
                "base_version_id": "ver-abc",
                "files": [
                    {
                        "file_name": "app.yaml",
                        "file_type": "APP_MANIFEST",
                        "file_path": "app.yaml",
                        "content": "app:\n  name: demo\n...",
                        "is_primary": False,
                        "order": 0,
                    }
                ],
            }
        }
    )


class TemplateVersionRejectRequest(BaseModel):
    """Optional body for `POST /template-versions/{id}/reject`."""
    reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional admin-provided reason; persisted on the version.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"reason": "app.yaml is missing required parameters"}
        }
    )


class TemplateVersionResponse(BaseModel):
    """Schema for template version response."""
    id: str = Field(..., description="Version ID")
    template_id: str = Field(..., description="Template ID")
    version: str = Field(..., description="Semantic version (e.g., 0.2.0)")
    git_commit_sha: str = Field(..., description="Git commit SHA")
    is_active: bool = Field(..., description="Whether this version is active")
    approval_status: str = Field(..., description="Approval status (pending/approved/rejected/deprecated)")
    approved_by_id: Optional[str] = Field(None, description="Admin user ID who approved/rejected this version")
    approved_at: Optional[datetime] = Field(None, description="Approval/rejection timestamp")
    rejection_reason: Optional[str] = Field(None, description="Optional admin-provided reason when rejected")
    created_at: datetime = Field(..., description="Creation timestamp")
    parameters: Optional[list[dict[str, Any]]] = Field(None, description="Template parameters from app.yaml")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "ver-123",
                "template_id": "tmpl-123",
                "version": "0.2.0",
                "git_commit_sha": "a1b2c3d4e5f6g7h8i9j0",
                "is_active": True,
                "approval_status": "approved",
                "approved_by_id": "user-admin",
                "approved_at": "2024-11-27T10:00:00Z",
                "created_at": "2024-11-27T10:00:00Z",
                "parameters": [
                    {
                        "name": "image",
                        "type": "string",
                        "default": "Ubuntu 22.04",
                        "required": True
                    }
                ]
            }
        }
    )


class TemplateQueueInfo(BaseModel):
    """Inlined template metadata for admin approval-queue rows."""
    id: str
    name: str
    owner_id: str
    visibility: str

    model_config = ConfigDict(from_attributes=True)


class TemplateVersionQueueItem(TemplateVersionResponse):
    """A single row of the admin approval queue.

    Extends `TemplateVersionResponse` with the parent template inlined so the
    admin UI can render the queue without a follow-up fetch per row, plus the
    parsed app.yaml `parameters` (resource requirements) so requirements can be
    shown directly in the list view.
    """
    template: TemplateQueueInfo
    parameters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Parameters parsed from app.yaml of this version (CPU/RAM/disk/etc).",
    )

    model_config = ConfigDict(from_attributes=True)


class TemplateVersionWithFilesResponse(TemplateVersionResponse):
    """Schema for template version response with file count."""
    file_count: int = Field(..., description="Number of files in this version")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "ver-123",
                "template_id": "tmpl-123",
                "version": "0.2.0",
                "git_commit_sha": "a1b2c3d4e5f6g7h8i9j0",
                "is_active": True,
                "approval_status": "approved",
                "approved_by_id": None,
                "approved_at": None,
                "created_at": "2024-11-27T10:00:00Z",
                "file_count": 3,
                "parameters": [
                    {
                        "name": "image",
                        "type": "string",
                        "default": "Ubuntu 22.04",
                        "required": True
                    }
                ]
            }
        }
    )
