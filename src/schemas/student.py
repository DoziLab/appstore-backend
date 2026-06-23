"""Schemas for the student self-service endpoints.

Deliberately narrower than the lecturer-facing ``DeploymentResponse`` —
students must never see other students' personal data (other group
members, teacher info, raw ``deployment_parameters``). Keeping the schemas
explicit prevents accidental widening as the lecturer schema evolves.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class StudentDeploymentInstanceSummary(BaseModel):
    """Minimal instance metadata for a student listing."""
    id: str = Field(..., description="Deployment instance ID")
    vm_name: Optional[str] = Field(None, description="Stack name / VM name")
    ip_address: Optional[str] = Field(None, description="Floating IP (if assigned)")

    model_config = ConfigDict(from_attributes=True)


class StudentTemplateSummary(BaseModel):
    """Minimal template metadata — name only, no app.yaml details."""
    name: Optional[str] = Field(None, description="Template name (e.g. 'Ansible Multi-User Ubuntu')")
    version: Optional[str] = Field(None, description="Template version (semver)")


class StudentDeploymentResponse(BaseModel):
    """One deployment as a student sees it.

    Intentionally omits ``deployment_parameters`` (contains teacher info,
    other students' personal data, app.yaml parameters), ``course_id``
    (irrelevant for students), and lecturer-specific fields.
    """
    id: str = Field(..., description="Deployment ID")
    name: str = Field(..., description="Deployment display name")
    status: str = Field(..., description="Deployment status (running, failed, ...)")
    template: StudentTemplateSummary = Field(..., description="Template summary")
    instances: list[StudentDeploymentInstanceSummary] = Field(
        default_factory=list,
        description="Instances of this deployment the student has any access to",
    )
    created_at: Optional[datetime] = Field(None, description="When the deployment was created")
    expires_at: Optional[datetime] = Field(None, description="When the deployment will be hard-deleted")

    model_config = ConfigDict(from_attributes=True)
