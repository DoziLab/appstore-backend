"""Schemas for the admin-only /lecturers endpoints."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LecturerListItem(BaseModel):
    """One row in the lecturer list view.

    Excludes any User row that owns neither templates nor OpenStack projects
    — those are students or freshly-created accounts and belong in a
    different UI.
    """

    id: str = Field(..., description="Local DB user id")
    external_id: str = Field(..., description="Keycloak sub claim")
    display_name: Optional[str] = Field(None, description="Cached display name from Keycloak")
    email: Optional[str] = Field(None, description="Cached email from Keycloak")
    username: Optional[str] = Field(None, description="Cached preferred_username from Keycloak")
    last_login_at: Optional[datetime] = Field(
        None,
        description="Last time the user's token was validated (proxy for 'still active in Keycloak')",
    )
    template_count: int = Field(..., description="Templates this user owns")
    deployment_count: int = Field(
        ...,
        description=(
            "Deployments whose deployment_parameters.teacher.id matches this user's external_id"
        ),
    )
    openstack_project_count: int = Field(
        ..., description="OpenStack projects this user owns"
    )

    model_config = ConfigDict(from_attributes=True)


class LecturerTemplateSummary(BaseModel):
    """Minimal template info for the detail view."""

    id: str
    name: str
    visibility: str
    version_count: int


class LecturerDeploymentSummary(BaseModel):
    """Minimal deployment info for the detail view."""

    id: str
    name: str
    status: str
    course_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime


class LecturerOpenstackProjectSummary(BaseModel):
    """Minimal OpenStack project info for the detail view."""

    id: str
    openstack_project_name: str
    region_name: str


class LecturerDetail(LecturerListItem):
    """Full detail view: list-row fields plus the owned/deployed resources."""

    templates: list[LecturerTemplateSummary]
    deployments: list[LecturerDeploymentSummary]
    openstack_projects: list[LecturerOpenstackProjectSummary]


class LecturerDeleteResponse(BaseModel):
    """Response of DELETE /lecturers/{id} — the actual work is async."""

    task_id: str = Field(..., description="Celery task id for the cascade delete")
    user_id: str = Field(..., description="User row scheduled for deletion")
    deployment_count: int = Field(
        ..., description="Number of deployments the cascade will tear down"
    )
    template_count: int = Field(
        ..., description="Number of templates the cascade will remove"
    )
