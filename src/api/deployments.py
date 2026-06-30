"""Deployment API endpoints."""
from uuid import UUID
import asyncio
import json
from fastapi import APIRouter, status, Query, Depends, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from src.core.exceptions import NotFoundException
from src.models.user import UserRole, User
from src.core.dependencies import DBSession
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import RequestID, Pagination, CurrentUser, require_roles
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.schemas.deployment import DeploymentResponse, DeploymentCreate, DeploymentExtend, DeploymentRedeployRequest
from src.services.deployment_service import DeploymentService
from src.services.deployment_log_service import DeploymentLogService
from src.services.openstack_heat_service import HeatStackService
from src.schemas.deployment import (
    DeploymentLogResponse,
    DeploymentCredentialEntry,
    DeploymentInstanceCredentials,
    DeploymentCredentialsResponse,
)
from src.tasks.deploy_tasks import delete_deployment as delete_deployment_task
from src.tasks.deploy_tasks import restart_deployment as restart_deployment_task
from src.tasks.deploy_tasks import redeploy_instance as redeploy_instance_task
from src.tasks.deploy_tasks import redeploy_deployment as redeploy_deployment_task
from src.models.deployment import DeploymentStatus, Deployment
from src.models.deployment_instance import DeploymentInstance, DeploymentInstanceStatus
from src.models.deployment_instance_access import DeploymentInstanceAccess
from src.models.template_version import TemplateVersion

router = APIRouter(
    prefix="/deployments",
    tags=["deployments"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER))],  # All endpoints require at least LECTURER role
)


def get_deployment_owner_id(deployment: Deployment, db) -> str:
    """Extract deployment owner's user_id from deployment_parameters.

    Args:
        deployment: Deployment model with deployment_parameters JSON
        db: Database session

    Returns:
        Local user_id of the deployment owner (teacher)

    Raises:
        HTTPException: If teacher information is missing or user not found
    """
    try:
        if not deployment.deployment_parameters:
            raise ValueError("Deployment parameters are missing")
        params = json.loads(deployment.deployment_parameters)
        teacher_info = params.get("teacher", {})
        teacher_keycloak_id = teacher_info.get("id")

        if not teacher_keycloak_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Deployment missing teacher information"
            )

        # Map Keycloak ID to local user ID
        teacher_user = db.query(User).filter(User.external_id == teacher_keycloak_id).first()

        if not teacher_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Teacher user not found for Keycloak ID {teacher_keycloak_id}"
            )

        return teacher_user.id

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid deployment_parameters JSON"
        )


def authorize_deployment_access(
    deployment: Deployment,
    user: dict,
    openstack_project_id: UUID | None,
    db,
) -> None:
    """Authorize a non-admin user to access a single deployment.

    Admins bypass all checks. Non-admins must:
    1. Pass an ``openstack_project_id`` query parameter (else 400).
    2. Be the deployment's owner (teacher.id maps to their local user_id; else 403).
    3. Have the deployment belong to the project they're currently scoped to (else 403).

    The same three checks are needed by every per-deployment endpoint
    (get/logs/stream/credentials/stack/restart/delete), so they live here once
    instead of being copy-pasted seven times.

    Args:
        deployment: The Deployment row in question.
        user: ``CurrentUser`` dict (with ``roles`` and ``user_id``).
        openstack_project_id: Query parameter from the request; ``None`` for admins is fine.
        db: Database session, forwarded to ``get_deployment_owner_id``.

    Raises:
        HTTPException 400: Non-admin caller did not pass ``openstack_project_id``.
        HTTPException 403: Non-admin caller is not the owner, or the deployment
            belongs to a different OpenStack project.
    """
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    if is_admin:
        return

    if openstack_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="openstack_project_id query parameter is required",
        )

    owner_id = get_deployment_owner_id(deployment, db)
    if user["user_id"] != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this deployment",
        )

    if str(deployment.openstack_project_id) != str(openstack_project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Deployment belongs to a different OpenStack project",
        )


@router.get("")
async def list_deployments(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    course_id: UUID | None = Query(None, description="Filter by course ID"),
    template_id: UUID | None = Query(None, description="Filter by template ID"),
    status_filter: str | None = Query(None, description="Filter by deployment status (e.g., RUNNING, FAILED)", alias="status"),
    openstack_project_id: UUID | None = Query(
        None,
        description=(
            "OpenStack project (local DB id) whose deployments to list. "
            "Required for non-admin users; ignored for admins unless provided."
        ),
    ),
):
    """List all deployments for the current user.

    Fetches deployments from database and enriches them with current OpenStack stack status.
    Only shows deployments created through the App Store, not all OpenStack resources.

    Returns deployment information including:
    - Deployment metadata (name, mode, parameters)
    - Current status from database
    - Associated course and template information
    - OpenStack stack ID (if available)

    Optional filters:
    - Course ID: Only show deployments for a specific course
    - Template ID: Only show deployments using a specific template
    - Status: Filter by deployment status (e.g., RUNNING, FAILED)

    Authorization & visibility:
    - Admins see all deployments (optionally filtered by openstack_project_id).
    - Non-admins (lecturers) MUST pass openstack_project_id and see only the
      deployments they own (teacher.id == them) within that project.

    Returns paginated results with total count.
    """

    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]

    # Non-admins must scope by OpenStack project; otherwise we'd be in the same
    # situation as before (lecturer seeing every other lecturer's deployments).
    if not is_admin and openstack_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="openstack_project_id query parameter is required",
        )

    # Validate that the project belongs to the requesting non-admin user.
    if not is_admin and openstack_project_id is not None:
        openstack_repo = OpenstackProjectRepository(db)
        proj = openstack_repo.get_by_id(str(openstack_project_id))
        if not proj or proj.owner_user_id != user["user_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="OpenStack project does not belong to user",
            )

    query = db.query(Deployment)

    # Apply filters
    if course_id:
        query = query.filter(Deployment.course_id == str(course_id))

    if template_id:
        query = query.join(TemplateVersion).filter(TemplateVersion.template_id == template_id)

    if openstack_project_id is not None:
        query = query.filter(Deployment.openstack_project_id == str(openstack_project_id))

    if status_filter:
        try:
            status_enum = DeploymentStatus(status_filter.lower())
            query = query.filter(Deployment.status == status_enum)
        except ValueError:
            # Invalid status filter, return empty result
            return ResponseBuilder.paginated(
                data=[],
                page=pagination.page,
                page_size=pagination.page_size,
                total=0,
                message=f"Invalid status filter: {status_filter}",
                request_id=request_id,
            )

    if is_admin:
        # Admins see everything; paginate in SQL.
        total = query.count()
        deployments = (
            query
            .order_by(Deployment.created_at.desc())
            .offset((pagination.page - 1) * pagination.page_size)
            .limit(pagination.page_size)
            .all()
        )
    else:
        # Non-admin: project filter already applied in SQL above. Owner-by-teacher
        # lives in deployment_parameters JSON, so we filter in Python via the
        # existing get_deployment_owner_id helper. Deployments with malformed or
        # missing teacher info are silently dropped so a single broken record
        # cannot break the whole listing.
        all_deployments = query.order_by(Deployment.created_at.desc()).all()
        owned: list[Deployment] = []
        for d in all_deployments:
            try:
                if get_deployment_owner_id(d, db) == user["user_id"]:
                    owned.append(d)
            except (HTTPException, ValueError, json.JSONDecodeError):
                continue
        total = len(owned)
        start = (pagination.page - 1) * pagination.page_size
        deployments = owned[start : start + pagination.page_size]
    
    # Convert to response format
    deployment_list = []
    for deployment in deployments:
        deployment_dict = DeploymentResponse.model_validate(deployment).model_dump(mode="json")
        
        # Add related objects
        deployment_dict["template_version"] = {
            "id": str(deployment.template_version.id),
            "version": deployment.template_version.version,
            "template_id": str(deployment.template_version.template_id),
            "template_name": deployment.template_version.template.name if deployment.template_version.template else None,
        } if deployment.template_version else None
        
        deployment_list.append(deployment_dict)
    
    return ResponseBuilder.paginated(
        data=deployment_list,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
        message=f"Retrieved {len(deployment_list)} deployments (total: {total})",
        request_id=request_id,
    )

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_deployment(
    deployment_data: DeploymentCreate,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """Create a new deployment (One-Click Deployment).
    
    Initiates deployment of a template version to a course (Keycloak group).
    The deployment is queued and processed asynchronously via Celery.
    
    **Authorization:** Requires ADMIN or LECTURER role.
    
    Args:
        deployment_data: Deployment creation request with template_id, course_id (Keycloak group ID), stack_assignments, and teacher
        db: Database session
        request_id: Request correlation ID
        user: Authenticated user with required role (auto-validated)
        
    Returns:
        Created deployment with status QUEUED
    """
    service = DeploymentService(db)
    is_admin = UserRole.ADMIN.value in user.get("roles", [])
    deployment = service.create_deployment(
        deployment_data,
        request_id=request_id,
        is_admin=is_admin,
    )
    
    # Convert SQLAlchemy model to response schema
    deployment_response = DeploymentResponse.model_validate(deployment)
    
    return ResponseBuilder.created(
        data=deployment_response.model_dump(mode="json"),
        message="Deployment created and queued for processing",
        request_id=request_id,
    )


@router.get("/{deployment_id}")
async def get_deployment(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    openstack_project_id: UUID | None = Query(
        None,
        description=(
            "OpenStack project (local DB id) the deployment must belong to. "
            "Required for non-admin users."
        ),
    ),
):
    """Get detailed information about a single deployment.

    Returns complete deployment details including:
    - Deployment metadata and configuration
    - Current status and timestamps
    - Associated template version and course
    - OpenStack Heat stack information (if available)
    - Deployment instances with access URLs

    **Authorization:** Owner (lecturer) or Admin only. Non-admin callers must
    additionally pass openstack_project_id matching the deployment; cross-project
    access via direct URL is rejected with 403.

    Args:
        deployment_id: ID of the deployment
        db: Database session
        request_id: Request correlation ID
        user: Authenticated user

    Returns:
        Detailed deployment information with instances

    Raises:
        NotFoundException: If deployment does not exist
        HTTPException: If user lacks permission to access this deployment
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    # Authorization: admins see all; lecturers must own the deployment AND be
    # currently scoped to the OpenStack project the deployment lives in.
    authorize_deployment_access(deployment, user, openstack_project_id, db)

    # Build response with deployment details
    deployment_dict = DeploymentResponse.model_validate(deployment).model_dump(mode="json")
    
    # Add related objects
    deployment_dict["template_version"] = {
        "id": str(deployment.template_version.id),
        "version": deployment.template_version.version,
        "template_id": str(deployment.template_version.template_id),
        "template_name": deployment.template_version.template.name if deployment.template_version.template else None,
    } if deployment.template_version else None
    
    # Add instances with access URLs
    deployment_dict["instances"] = [
        {
            "id": str(instance.id),
            "instance_name": instance.vm_name,
            "openstack_instance_id": instance.openstack_server_id,
            "status": instance.status.value if instance.status else None,
            "ip_address": instance.ip_address,
            "flavor": instance.flavor,
            "access_urls": [
                {
                    "id": str(access.id),
                    "access_type": access.access_type.value if access.access_type else None,
                    "connection_url": access.connection_url,
                    "username": access.username,
                    "port": access.port,
                    "is_active": access.is_active,
                }
                for access in (instance.access_methods or [])
            ],
            "created_at": instance.created_at.isoformat() if hasattr(instance.created_at, 'isoformat') else instance.created_at,
            "updated_at": instance.updated_at.isoformat() if hasattr(instance.updated_at, 'isoformat') else instance.updated_at,
        }
        for instance in (deployment.instances or [])
    ]
    
    return ResponseBuilder.success(
        data=deployment_dict,
        message="Deployment details retrieved successfully",
        request_id=request_id,
    )


@router.get("/{deployment_id}/logs", response_model=dict)
async def get_deployment_logs(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """
    Get all logs for a specific deployment.

    Returns logs in chronological order (oldest first).

    Args:
        deployment_id: ID of the deployment
        db: Database session
        request_id: Request ID for tracing

    Returns:
        List of deployment log entries

    Raises:
        NotFoundException: If deployment does not exist
        HTTPException: If access is forbidden
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)
    
    # Get logs
    log_service = DeploymentLogService(db)
    logs = log_service.get_deployment_logs(deployment_id)
    
    return ResponseBuilder.success(
        data=[DeploymentLogResponse.model_validate(log) for log in logs],
        message=f"Retrieved {len(logs)} log entries for deployment",
        request_id=request_id
    )


@router.get("/{deployment_id}/logs/stream")
async def stream_deployment_logs(
    deployment_id: str,
    db: DBSession,
    user: CurrentUser,
    since_id: str = Query(None, description="Only send logs newer than this log ID"),
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """
    Stream deployment logs as Server-Sent Events (SSE).

    Sends all existing logs immediately, then polls for new ones every second
    until the deployment reaches a terminal state (RUNNING, FAILED, DELETED).
    The stream closes automatically when done.

    Implementation notes:
      * Authorization runs against the request's DB session, but the polling
        loop opens its OWN fresh SessionLocal each tick. Reusing the request
        session would never see commits from the Celery worker (the session
        caches identity-mapped objects within a single transaction).
      * Sync SQLAlchemy calls are wrapped in run_in_threadpool so the event
        loop stays free for other SSE clients.
      * A heartbeat comment is sent every ~15s so proxies/browsers don't
        consider the connection dead during long Ansible phases.
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)

    TERMINAL_STATUSES = {"RUNNING", "FAILED", "DELETED", "CANCELLED"}
    HEARTBEAT_EVERY_SECONDS = 15
    POLL_INTERVAL_SECONDS = 1

    # Snapshot the (immutable) deployment_id for the closure; do NOT capture
    # the ORM `deployment` object — it's bound to the request session which
    # closes when this handler returns.
    dep_id = deployment_id

    def _fetch_state(since_seen: set[str], since_id_param: str | None):
        """Open a fresh DB session, return (new_log_payloads, current_status).

        Runs in the threadpool so the event loop isn't blocked on DB I/O.
        """
        from src.core.database import SessionLocal
        local_db = SessionLocal()
        try:
            local_repo = DeploymentRepository(local_db)
            current = local_repo.get_by_id(dep_id)
            if current is None:
                return [], "DELETED"

            current_status = (
                current.status.value if hasattr(current.status, "value") else str(current.status)
            ).upper()

            local_log_service = DeploymentLogService(local_db)
            logs = local_log_service.get_deployment_logs(dep_id)

            # First iteration: seed seen-set from since_id if provided
            if since_id_param and not since_seen:
                for log in logs:
                    if str(log.id) == since_id_param:
                        break
                    since_seen.add(str(log.id))

            new_payloads: list[str] = []
            for log in logs:
                lid = str(log.id)
                if lid in since_seen:
                    continue
                since_seen.add(lid)
                new_payloads.append(json.dumps({
                    "id": lid,
                    "deployment_id": str(log.deployment_id),
                    "event_type": log.event_type.value if hasattr(log.event_type, "value") else str(log.event_type),
                    "message": log.message,
                    "level": log.level.value if hasattr(log.level, "value") else str(log.level),
                    "details": json.loads(log.details_json) if log.details_json else None,
                    "created_at": log.created_at.isoformat() if hasattr(log.created_at, "isoformat") else str(log.created_at),
                }))
            return new_payloads, current_status
        finally:
            local_db.close()

    async def event_generator():
        from fastapi.concurrency import run_in_threadpool

        seen_ids: set[str] = set()
        seconds_since_heartbeat = 0
        first = True

        try:
            while True:
                payloads, current_status = await run_in_threadpool(
                    _fetch_state, seen_ids, since_id if first else None
                )
                first = False

                for payload in payloads:
                    yield f"data: {payload}\n\n"
                    seconds_since_heartbeat = 0

                if current_status in TERMINAL_STATUSES:
                    yield "event: done\ndata: {}\n\n"
                    break

                if seconds_since_heartbeat >= HEARTBEAT_EVERY_SECONDS:
                    # SSE comment line — clients ignore it, proxies keep the socket alive.
                    yield ": ping\n\n"
                    seconds_since_heartbeat = 0

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                seconds_since_heartbeat += POLL_INTERVAL_SECONDS
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{deployment_id}/credentials", response_model=dict)
async def get_deployment_credentials(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Return generated user credentials for a deployment.

    Accessible to the lecturer who owns the deployment or any admin. Passwords
    are decrypted on read by the EncryptedString TypeDecorator on the model.
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)

    instances = (
        db.query(DeploymentInstance)
        .filter(DeploymentInstance.deployment_id == deployment_id)
        .all()
    )

    instance_payloads = [
        DeploymentInstanceCredentials(
            instance_id=instance.id,
            vm_name=instance.vm_name,
            openstack_stack_id=instance.openstack_server_id,
            accesses=[
                DeploymentCredentialEntry(
                    id=access.id,
                    access_type=access.access_type.value,
                    username=access.username,
                    password=access.password,
                    ssh_private_key=access.ssh_private_key,
                    connection_url=access.connection_url,
                    port=access.port,
                    group_id=access.group_id,
                    # Frontend renders Dozent/Gruppen tabs from group_id + group_name.
                    # group_id=NULL → admin/lecturer row → "Dozent" tab.
                    # group_id=set → student group row → "Gruppen" tab, accordion by group_name.
                    group_name=access.group.name if access.group else None,
                )
                for access in instance.access_methods
            ],
        )
        for instance in instances
    ]

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
    "/{deployment_id}/credentials/access/{access_id}/ssh-key",
    response_class=PlainTextResponse,
)
async def download_ssh_private_key(
    deployment_id: str,
    access_id: str,
    db: DBSession,
    user: CurrentUser,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Download an SSH private key as a downloadable file.

    Returned as ``application/x-pem-file`` with a ``Content-Disposition``
    attachment header so the browser saves it as ``id_ed25519`` rather than
    rendering the PEM in-line. Accessible to the deployment owner (lecturer)
    or any admin.
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)

    access = (
        db.query(DeploymentInstanceAccess)
        .join(DeploymentInstance, DeploymentInstance.id == DeploymentInstanceAccess.deployment_instance_id)
        .filter(
            DeploymentInstanceAccess.id == access_id,
            DeploymentInstance.deployment_id == deployment_id,
        )
        .first()
    )
    if not access:
        raise NotFoundException(f"Access entry {access_id} not found for deployment {deployment_id}")
    if not access.ssh_private_key:
        raise HTTPException(status_code=404, detail="No SSH private key available for this access entry")

    # OpenSSH PEM contents — decrypted automatically by EncryptedString on read
    filename = f"id_ed25519_{(access.username or 'user')}"
    return PlainTextResponse(
        content=access.ssh_private_key,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{deployment_id}/stack")
async def get_deployment_stack(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Get OpenStack Heat stack information for a deployment.

    Returns current stack status, resources, and outputs.

    Args:
        deployment_id: ID of the deployment
        db: Database session
        request_id: Request ID for tracing
        user: Authenticated user

    Returns:
        Stack information including status and resources

    Raises:
        NotFoundException: If deployment does not exist
        HTTPException: If stack information cannot be retrieved or access is forbidden
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)
    
    if not deployment.openstack_stack_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Heat stack associated with this deployment"
        )
    
    # Use the deployment's persisted OpenStack project (FK) instead of
    # re-deriving it from teacher.id — same reason as in deploy_tasks: the
    # old [0]-pick was wrong whenever a user had more than one project.
    openstack_project = deployment.openstack_project
    if not openstack_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment {deployment_id} has no openstack_project_id set",
        )

    try:
        heat_service = HeatStackService(openstack_project)
        
        # Get stack details
        stack_info = heat_service.get_stack(deployment.openstack_stack_id)
        
        # Get stack resources
        try:
            resources = heat_service.get_stack_resources(deployment.openstack_stack_id)
        except Exception:
            resources = []
        
        # Get stack outputs
        try:
            outputs = heat_service.get_stack_outputs(deployment.openstack_stack_id)
        except Exception:
            outputs = {}
        
        return ResponseBuilder.success(
            data={
                "stack": stack_info,
                "resources": resources,
                "outputs": outputs
            },
            message="Stack information retrieved successfully",
            request_id=request_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve stack information: {str(e)}"
        )


@router.post(
    "/{deployment_id}/restart",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Restart a deployment",
    responses={
        202: {"description": "Restart requested; operation in progress"},
        400: {"description": "Deployment is already in a transitional state"},
        403: {"description": "Forbidden - not owner or insufficient role"},
        404: {"description": "Deployment not found"},
        500: {"description": "Failed to enqueue restart task"},
    },
)
async def restart_deployment(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Restart a deployment by updating the Heat stack.

    Triggers a Heat stack update to restart the deployment's resources.
    This is useful for recovering from transient errors or applying updates.

    **Authorization:** Owner (lecturer) or Admin only.

    Args:
        deployment_id: ID of the deployment to restart
        db: Database session
        request_id: Request correlation ID
        user: Authenticated user

    Returns:
        Acknowledgment that restart has been queued

    Raises:
        NotFoundException: If deployment does not exist
        HTTPException: If user lacks permission or deployment is in invalid state
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)
    
    # Validate deployment state: cannot restart if already in a transitional state
    transitional_states = [DeploymentStatus.CREATING, DeploymentStatus.DELETING, DeploymentStatus.RESTARTING]
    if deployment.status in transitional_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot restart deployment in {deployment.status.value} state. Please wait for current operation to complete."
        )
    
    # Verify deployment has an OpenStack stack
    if not deployment.openstack_stack_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deployment has no associated OpenStack stack to restart"
        )
    
    # Enqueue Celery task to perform restart asynchronously
    try:
        restart_deployment_task.delay(deployment_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue restart task",
        )
    
    return ResponseBuilder.success(
        data={"deployment_id": deployment_id, "status": "restart_queued"},
        message="Restart requested; operation is in progress",
        request_id=request_id,
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "/{deployment_id}/redeploy",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Redeploy every VM in a deployment",
    responses={
        202: {"description": "Redeploy requested; operation in progress"},
        400: {"description": "Deployment is in an invalid state or has no instances"},
        403: {"description": "Forbidden - not owner or insufficient role"},
        404: {"description": "Deployment not found"},
        500: {"description": "Failed to enqueue redeploy task"},
    },
)
async def redeploy_deployment_endpoint(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    payload: DeploymentRedeployRequest | None = None,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Destroy-and-recreate every VM (``DeploymentInstance``) in this
    deployment, one after another, optionally with overridden parameters.

    Unlike :func:`restart_deployment` (which only triggers a Heat
    ``update_stack`` on the existing stack), this rebuilds each VM from
    scratch: Heat stack deleted → Heat stack recreated → Ansible re-run →
    credentials regenerated (unless ``preserve_credentials=true``). Use it
    when a config / template parameter changed and you want the change to
    actually take effect.

    Sequential by design — running them in parallel risks tripping the
    OpenStack project quota mid-class. The parent deployment stays in
    ``RUNNING`` between instances so the UI can show per-VM progress and
    siblings stay reachable.

    **Authorization:** Owner (lecturer) or Admin only.
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)

    transitional_states = [
        DeploymentStatus.CREATING,
        DeploymentStatus.DELETING,
        DeploymentStatus.RESTARTING,
    ]
    if deployment.status in transitional_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot redeploy deployment in {deployment.status.value} state. "
                f"Please wait for the current operation to complete."
            ),
        )

    # If any instance is already mid-redeploy, refuse — two redeploy tasks racing
    # the same Heat stack would corrupt deployment.openstack_stack_id and leak
    # stacks. We only need to find ONE such instance to reject.
    in_flight = (
        db.query(DeploymentInstance.id)
        .filter(
            DeploymentInstance.deployment_id == deployment_id,
            DeploymentInstance.status == DeploymentInstanceStatus.REDEPLOYING,
        )
        .first()
    )
    if in_flight is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A redeploy is already in progress for at least one instance "
                "in this deployment; wait for it to finish before queuing another."
            ),
        )

    instance_count = (
        db.query(DeploymentInstance)
        .filter(DeploymentInstance.deployment_id == deployment_id)
        .count()
    )
    if instance_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deployment has no instances to redeploy",
        )

    body = payload or DeploymentRedeployRequest()
    # We deliberately don't wrap .delay() in a broad except: a broker outage or
    # a non-serialisable override value should surface as the underlying error
    # (Celery's own message) so the caller can diagnose it, instead of being
    # masked behind a generic "Failed to enqueue redeploy task".
    redeploy_deployment_task.delay(
        deployment_id,
        deployment_parameter_overrides=body.deployment_parameter_overrides,
        instance_parameter_overrides=body.instance_parameter_overrides,
        preserve_credentials=body.preserve_credentials,
    )

    return ResponseBuilder.success(
        data={
            "deployment_id": deployment_id,
            "instance_count": instance_count,
            "status": "redeploy_queued",
            "preserve_credentials": body.preserve_credentials,
        },
        message=f"Redeploy requested for {instance_count} instance(s); operation in progress",
        request_id=request_id,
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.post(
    "/{deployment_id}/instances/{instance_id}/redeploy",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Redeploy a single VM (DeploymentInstance)",
    responses={
        202: {"description": "Redeploy requested; operation in progress"},
        400: {"description": "Deployment or instance is in an invalid state"},
        403: {"description": "Forbidden - not owner or insufficient role"},
        404: {"description": "Deployment or instance not found"},
        500: {"description": "Failed to enqueue redeploy task"},
    },
)
async def redeploy_instance_endpoint(
    deployment_id: str,
    instance_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    payload: DeploymentRedeployRequest | None = None,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Destroy-and-recreate exactly one VM inside an existing deployment.

    Use this when one VM is wedged, or to apply a config change to a
    single group without touching its siblings. The parent deployment
    stays in ``RUNNING`` for the duration — only the target instance
    flips to ``REDEPLOYING``.

    Body parameters mirror the deployment-wide endpoint, with one
    semantic shift: ``deployment_parameter_overrides`` is treated as the
    full override for this one VM (since there's only one in scope).
    ``instance_parameter_overrides`` is ignored here — pass per-VM
    parameters directly in ``deployment_parameter_overrides``.

    **Authorization:** Owner (lecturer) or Admin only.
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)

    transitional_states = [
        DeploymentStatus.CREATING,
        DeploymentStatus.DELETING,
        DeploymentStatus.RESTARTING,
    ]
    if deployment.status in transitional_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot redeploy instance while deployment is in {deployment.status.value} state."
            ),
        )

    instance = (
        db.query(DeploymentInstance)
        .filter(
            DeploymentInstance.id == instance_id,
            DeploymentInstance.deployment_id == deployment_id,
        )
        .first()
    )
    if not instance:
        raise NotFoundException(
            f"Instance {instance_id} not found in deployment {deployment_id}"
        )

    # Refuse if this instance is already mid-redeploy — a second task racing the
    # first one would delete a stack the first already removed (raises and flips
    # status to FAILED) and the survivors would corrupt deployment.openstack_stack_id.
    if instance.status == DeploymentInstanceStatus.REDEPLOYING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Instance {instance_id} is already being redeployed; "
                "wait for the current operation to finish."
            ),
        )

    body = payload or DeploymentRedeployRequest()
    # No broad except around .delay() — see redeploy_deployment_endpoint above.
    redeploy_instance_task.delay(
        deployment_id,
        instance_id,
        deployment_parameter_overrides=body.deployment_parameter_overrides,
        preserve_credentials=body.preserve_credentials,
    )

    return ResponseBuilder.success(
        data={
            "deployment_id": deployment_id,
            "instance_id": instance_id,
            "status": "redeploy_queued",
            "preserve_credentials": body.preserve_credentials,
        },
        message="Redeploy requested for instance; operation in progress",
        request_id=request_id,
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.patch(
    "/{deployment_id}/extend",
    summary="Extend a deployment's lifetime",
    responses={
        200: {"description": "Lifetime extended; new expires_at returned"},
        400: {"description": "Deployment is already deleted or runtime_months invalid"},
        403: {"description": "Forbidden - not owner or insufficient role"},
        404: {"description": "Deployment not found"},
    },
)
async def extend_deployment(
    deployment_id: str,
    payload: DeploymentExtend,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Push the deployment's ``expires_at`` out by ``runtime_months`` months.

    Anchored on ``max(now, current_expires_at)``: if the deployment is still
    valid, the new window stacks on top of its existing end date; if it has
    already expired (but not yet been swept by the daily beat job), the
    extension counts from now. Companion ``expiry_warning_at`` is recomputed
    so the UI banner timing matches the new lifetime.

    **Authorization:** Owner (lecturer) or Admin only.
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)

    service = DeploymentService(db)
    updated = service.extend_deployment(
        deployment_id=deployment_id,
        runtime_months=payload.runtime_months,
    )

    return ResponseBuilder.success(
        data={
            "deployment_id": str(updated.id),
            "expires_at": updated.expires_at.isoformat() if updated.expires_at else None,
            "expiry_warning_at": updated.expiry_warning_at.isoformat() if updated.expiry_warning_at else None,
            "runtime_months_added": payload.runtime_months,
        },
        message=f"Deployment lifetime extended by {payload.runtime_months} months",
        request_id=request_id,
    )


@router.delete(
    "/{deployment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a deployment",
    responses={
        204: {"description": "Deletion requested; operation in progress"},
        403: {"description": "Forbidden - not owner or insufficient role"},
        404: {"description": "Deployment not found"},
        500: {"description": "Failed to enqueue deletion task or internal error"},
    },
)
async def delete_deployment(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    openstack_project_id: UUID | None = Query(
        None,
        description="OpenStack project (local DB id) the deployment must belong to. Required for non-admin users.",
    ),
):
    """Request deletion of a deployment.

    Flips the deployment's status to ``DELETING`` *immediately* — this acts
    as the cooperative-cancel flag that any in-flight ``deploy_stack`` task
    polls between phases. The task then bails out cleanly, persisting every
    Heat stack it managed to create before. After flipping, the
    ``delete_deployment`` Celery task is enqueued; it picks up those stack
    ids from ``openstack_stack_id`` and tears them down.
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    authorize_deployment_access(deployment, user, openstack_project_id, db)

    # Set DELETING up front so the deploy task's status-polling checkpoints
    # see it before we enqueue the actual cleanup task. Skipping the update
    # if we're already DELETING/DELETED keeps the call idempotent.
    if deployment.status not in (DeploymentStatus.DELETING, DeploymentStatus.DELETED):
        deployment_repo.update_status(deployment_id, DeploymentStatus.DELETING)

    # Enqueue Celery task to perform deletion asynchronously
    try:
        delete_deployment_task.delay(deployment_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue deletion task",
        )

    return ResponseBuilder.no_content(
        message="Deletion requested; cancel-and-cleanup is in progress",
        request_id=request_id,
    )
