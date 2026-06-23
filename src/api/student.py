"""Student self-service API endpoints.

Scope: A logged-in student (Keycloak role ``student``) can only do TWO things:

1. List deployments where they personally are a member of at least one group
   that has credentials for that deployment.
2. Fetch ONLY their group's credentials — never the lecturer's admin
   credentials, never another group's credentials.
3. Download an SSH private key — same access scope.

Authorization model:
- Router-level guard: ``require_roles(UserRole.STUDENT)``. Lecturers / admins
  are explicitly NOT allowed on these routes (they have their own).
- Per-deployment scope: a single SQL join through CourseMember →
  GroupMember → CourseGroup → DeploymentInstanceAccess.group_id determines
  which access rows the student may see. Rows with ``group_id IS NULL``
  (teacher/admin credentials) are always filtered out.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import joinedload

from src.core.dependencies import CurrentUser, DBSession, RequestID, require_roles
from src.core.exceptions import NotFoundException
from src.core.response_builder import ResponseBuilder
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.deployment import Deployment, DeploymentStatus
from src.models.deployment_instance import DeploymentInstance
from src.models.deployment_instance_access import DeploymentInstanceAccess
from src.models.group_member import GroupMember
from src.models.user import UserRole
from src.schemas.deployment import (
    DeploymentCredentialEntry,
    DeploymentCredentialsResponse,
    DeploymentInstanceCredentials,
)
from src.schemas.student import (
    StudentDeploymentInstanceSummary,
    StudentDeploymentResponse,
    StudentTemplateSummary,
)


router = APIRouter(
    prefix="/student",
    tags=["student"],
    # Hard router-level guard: only callers with the STUDENT role pass here.
    # Lecturers/admins get 403 on these routes — they have their own.
    dependencies=[Depends(require_roles(UserRole.STUDENT))],
)


def _allowed_group_ids_for_deployment(
    db,
    student_user_id: str,
    deployment_id: str,
) -> set[str]:
    """Return the set of ``course_groups.id`` the student belongs to AND
    that have at least one access entry on the given deployment.

    Empty set means: student has no access to this deployment.
    """
    rows = (
        db.query(CourseGroup.id)
        .join(GroupMember, GroupMember.group_id == CourseGroup.id)
        .join(CourseMember, CourseMember.id == GroupMember.course_member_id)
        .join(
            DeploymentInstanceAccess,
            DeploymentInstanceAccess.group_id == CourseGroup.id,
        )
        .join(
            DeploymentInstance,
            DeploymentInstance.id == DeploymentInstanceAccess.deployment_instance_id,
        )
        .filter(
            CourseMember.user_id == student_user_id,
            CourseMember.left_at.is_(None),
            DeploymentInstance.deployment_id == deployment_id,
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


@router.get("/deployments")
async def list_student_deployments(
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """List deployments where the student is in a group that has credentials.

    Returns a trimmed view (``StudentDeploymentResponse``) — no
    ``deployment_parameters``, no lecturer info, no other groups' details.
    """
    student_user_id = user["user_id"]

    deployments = (
        db.query(Deployment)
        .options(joinedload(Deployment.template_version))
        .join(DeploymentInstance, DeploymentInstance.deployment_id == Deployment.id)
        .join(
            DeploymentInstanceAccess,
            DeploymentInstanceAccess.deployment_instance_id == DeploymentInstance.id,
        )
        .join(CourseGroup, CourseGroup.id == DeploymentInstanceAccess.group_id)
        .join(GroupMember, GroupMember.group_id == CourseGroup.id)
        .join(CourseMember, CourseMember.id == GroupMember.course_member_id)
        .filter(
            CourseMember.user_id == student_user_id,
            CourseMember.left_at.is_(None),
            Deployment.status != DeploymentStatus.DELETED,
        )
        .distinct()
        .all()
    )

    payload = []
    for d in deployments:
        template = d.template_version.template if d.template_version else None
        # Only surface instances that have at least one access row tied to a
        # group the student belongs to — same scope as the credentials filter.
        allowed_groups = _allowed_group_ids_for_deployment(db, student_user_id, d.id)
        visible_instances = [
            inst for inst in d.instances
            if any(
                a.group_id in allowed_groups for a in inst.access_methods
            )
        ]
        payload.append(
            StudentDeploymentResponse(
                id=d.id,
                name=d.name,
                status=d.status.value if hasattr(d.status, "value") else str(d.status),
                template=StudentTemplateSummary(
                    name=template.name if template else None,
                    version=d.template_version.version if d.template_version else None,
                ),
                instances=[
                    StudentDeploymentInstanceSummary(
                        id=inst.id,
                        vm_name=inst.vm_name,
                        ip_address=inst.ip_address,
                    )
                    for inst in visible_instances
                ],
                created_at=d.created_at,
                expires_at=d.expires_at,
            ).model_dump()
        )

    return ResponseBuilder.success(
        data=payload,
        message=f"Retrieved {len(payload)} deployment(s)",
        request_id=request_id,
    )


@router.get("/deployments/{deployment_id}/credentials")
async def get_student_credentials(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """Return only the credentials the student is entitled to see.

    Filters ``DeploymentInstanceAccess`` by the student's group memberships.
    Admin credentials (``group_id IS NULL``) are never returned.
    """
    student_user_id = user["user_id"]

    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    allowed_groups = _allowed_group_ids_for_deployment(db, student_user_id, deployment_id)
    if not allowed_groups:
        # Either student is not a member of any group on this deployment, or
        # the deployment doesn't exist in their world. Treat both as 403 —
        # 404 would leak existence.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this deployment",
        )

    instances = (
        db.query(DeploymentInstance)
        .filter(DeploymentInstance.deployment_id == deployment_id)
        .all()
    )

    instance_payloads = []
    for inst in instances:
        visible_accesses = [
            a for a in inst.access_methods
            if a.group_id is not None and a.group_id in allowed_groups
        ]
        if not visible_accesses:
            continue
        instance_payloads.append(
            DeploymentInstanceCredentials(
                instance_id=inst.id,
                vm_name=inst.vm_name,
                openstack_stack_id=inst.openstack_server_id,
                accesses=[
                    DeploymentCredentialEntry(
                        id=a.id,
                        access_type=a.access_type.value,
                        username=a.username,
                        password=a.password,
                        ssh_private_key=a.ssh_private_key,
                        connection_url=a.connection_url,
                        port=a.port,
                    )
                    for a in visible_accesses
                ],
            )
        )

    payload = DeploymentCredentialsResponse(
        deployment_id=deployment_id,
        instances=instance_payloads,
    )

    return ResponseBuilder.success(
        data=payload.model_dump(),
        message=f"Retrieved credentials for {len(instance_payloads)} instance(s)",
        request_id=request_id,
    )


@router.get(
    "/deployments/{deployment_id}/credentials/access/{access_id}/ssh-key",
    response_class=PlainTextResponse,
)
async def download_student_ssh_key(
    deployment_id: str,
    access_id: str,
    db: DBSession,
    user: CurrentUser,
):
    """Download an SSH private key tied to the student's own group.

    Mirrors the lecturer-facing endpoint, but with stricter ownership: the
    access row's ``group_id`` MUST be one of the student's group
    memberships. Admin rows (``group_id IS NULL``) are never reachable.
    """
    student_user_id = user["user_id"]

    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    allowed_groups = _allowed_group_ids_for_deployment(db, student_user_id, deployment_id)
    if not allowed_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this deployment",
        )

    access = (
        db.query(DeploymentInstanceAccess)
        .join(
            DeploymentInstance,
            DeploymentInstance.id == DeploymentInstanceAccess.deployment_instance_id,
        )
        .filter(
            DeploymentInstanceAccess.id == access_id,
            DeploymentInstance.deployment_id == deployment_id,
        )
        .first()
    )
    if not access:
        raise NotFoundException(f"Access entry {access_id} not found for deployment {deployment_id}")
    # Stricter than the lecturer endpoint: the access row MUST belong to one
    # of the student's groups. Catches the case where a student tries an
    # access_id they technically know but doesn't belong to their group —
    # 403, not 404, because the row exists but is not theirs to see.
    if access.group_id is None or access.group_id not in allowed_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This access entry does not belong to your group",
        )
    if not access.ssh_private_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SSH private key available for this access entry",
        )

    filename = f"id_ed25519_{(access.username or 'user')}"
    return PlainTextResponse(
        content=access.ssh_private_key,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
