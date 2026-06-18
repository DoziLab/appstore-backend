"""Deployment schemas for request/response validation."""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, Any


class StudentInfo(BaseModel):
    """Student information from Keycloak."""
    id: str = Field(..., description="Keycloak user UUID")
    username: str = Field(..., description="Student username")
    email: str = Field(..., description="Student email")
    first_name: str = Field(..., description="Student first name")
    last_name: str = Field(..., description="Student last name")


class GroupInfo(BaseModel):
    """Group information with students."""
    group_name: str = Field(..., description="Group name")
    group_index: int = Field(..., description="Group index/number")
    students: list[StudentInfo] = Field(..., description="Students in this group")


class StackAssignment(BaseModel):
    """Stack assignment with groups."""
    stack_index: Optional[int] = Field(None, description="Stack index (for multiple stacks)")
    groups: list[GroupInfo] = Field(..., description="Groups assigned to this stack")


class TeacherInfo(BaseModel):
    """Teacher/lecturer information from Keycloak."""
    id: str = Field(..., description="Keycloak user UUID")
    username: str = Field(..., description="Teacher username")
    email: str = Field(..., description="Teacher email")
    first_name: str = Field(..., description="Teacher first name")
    last_name: str = Field(..., description="Teacher last name")


class DeploymentCreate(BaseModel):
    """Schema for creating a deployment."""
    name: str = Field(..., description="Deployment name for identification", max_length=255)
    template_version_id: str = Field(..., description="Template version ID to deploy")
    course_id: str = Field(..., description="Keycloak group ID for the course")
    openstack_project_id: str = Field(
        ...,
        description=(
            "OpenStack project (local DB primary key from openstack_projects.id, "
            "NOT the Keystone tenant UUID) this deployment should run against. "
            "Must belong to the requesting teacher."
        ),
    )

    # All template parameters — backend separates Heat vs Ansible automatically
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="All template parameters from app.yaml (Heat + Ansible). Backend splits them automatically."
    )

    # Stack assignments (for user_json generation)
    stack_assignments: list[StackAssignment] = Field(
        ...,
        description="Stack assignments with groups and students"
    )

    # Teacher info (for admin_credentials generation)
    teacher: TeacherInfo = Field(
        ...,
        description="Teacher/lecturer information for admin access"
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "SQL Kurs - Herbst 2026",
                "template_version_id": "uuid-der-template-version",
                "course_id": "keycloak-group-id",
                "heat_parameters": {
                    "image": "Ubuntu 22.04 2025-01",
                    "flavor": "gp1.small",
                    "network": "NAT",
                    "external_network": "DHBW",
                    "ssh_cidr": "141.72.0.0/16",
                    "web_cidr": "141.72.0.0/16"
                },
                "stack_assignments": [
                    {
                        "stack_index": 1,
                        "groups": [
                            {
                                "group_name": "Gruppe 1",
                                "group_index": 1,
                                "students": [
                                    {
                                        "id": "keycloak-uuid-1",
                                        "username": "max.mustermann",
                                        "email": "max@example.com",
                                        "first_name": "Max",
                                        "last_name": "Mustermann"
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "teacher": {
                    "id": "keycloak-teacher-uuid",
                    "username": "prof.berg",
                    "email": "berg@dhbw.de",
                    "first_name": "Prof.",
                    "last_name": "Berg"
                }
            }
        }
    )


class DeploymentResponse(BaseModel):
    """Schema for deployment response."""
    id: str = Field(..., description="Deployment ID")
    name: str = Field(..., description="Deployment name")
    template_version_id: str = Field(..., description="Template version ID")
    course_id: str = Field(..., description="Keycloak group ID for the course")
    status: str = Field(..., description="Current status")
    openstack_stack_id: Optional[str] = Field(None, description="OpenStack Heat stack ID")
    deployment_parameters: Optional[str] = Field(None, description="Heat template parameters as JSON string")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "deploy-123",
                "name": "SQL Kurs - Herbst 2026",
                "template_version_id": "version-123",
                "course_id": "keycloak-group-456",
                "status": "queued",
                "openstack_stack_id": None,
                "deployment_parameters": '{"image": "Ubuntu 22.04", "flavor": "gp1.small"}',
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )


class DeploymentLogResponse(BaseModel):
    """Schema for deployment log response."""
    id: str = Field(..., description="Log entry ID")
    deployment_id: str = Field(..., description="Deployment ID")
    event_type: str = Field(..., description="Event type")
    message: str = Field(..., description="Log message")
    level: str = Field(..., description="Log level (INFO, WARNING, ERROR)")
    details: Optional[dict[str, Any]] = Field(None, description="Additional details as JSON")
    request_id: Optional[str] = Field(None, description="Request ID for tracing")
    created_at: datetime = Field(..., description="Log timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "log-123",
                "deployment_id": "deploy-123",
                "event_type": "DEPLOYMENT_STARTED",
                "message": "Deployment task started",
                "level": "INFO",
                "details": {"task_id": "abc-123"},
                "request_id": "req-456",
                "created_at": "2024-11-27T10:00:00Z"
            }
        }
    )


class DeploymentCredentialEntry(BaseModel):
    """One credential entry for a deployment instance."""
    access_type: str = Field(..., description="Access type, e.g. ssh or database")
    username: Optional[str] = Field(None, description="Account username")
    password: Optional[str] = Field(None, description="Plaintext password (decrypted on read)")
    connection_url: Optional[str] = Field(None, description="Connection URL if applicable")
    port: Optional[int] = Field(None, description="Port number if applicable")

    model_config = ConfigDict(from_attributes=True)


class DeploymentInstanceCredentials(BaseModel):
    """Credentials grouped by deployment instance (one per Heat stack)."""
    instance_id: str = Field(..., description="Deployment instance ID")
    vm_name: Optional[str] = Field(None, description="Stack name / VM name")
    openstack_stack_id: Optional[str] = Field(None, description="OpenStack Heat stack ID")
    accesses: list[DeploymentCredentialEntry] = Field(..., description="Credential entries for this instance")


class DeploymentCredentialsResponse(BaseModel):
    """Response payload for GET /deployments/{id}/credentials."""
    deployment_id: str = Field(..., description="Deployment ID")
    instances: list[DeploymentInstanceCredentials] = Field(..., description="Per-instance credential bundles")

