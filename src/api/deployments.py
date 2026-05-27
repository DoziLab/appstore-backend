"""Deployment API endpoints."""
from uuid import UUID
import json
from fastapi import APIRouter, status, Query, Depends, HTTPException
from src.core.exceptions import NotFoundException
from src.models.user import UserRole, User
from src.core.dependencies import DBSession
from src.core.response_builder import ResponseBuilder
from src.core.dependencies import RequestID, Pagination, CurrentUser, require_roles
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.schemas.deployment import DeploymentResponse, DeploymentCreate
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
from src.models.deployment import DeploymentStatus, Deployment
from src.models.deployment_instance import DeploymentInstance
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


@router.get("")
async def list_deployments(
    pagination: Pagination,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
    course_id: UUID | None = Query(None, description="Filter by course ID"),
    template_id: UUID | None = Query(None, description="Filter by template ID"),
    status_filter: str | None = Query(None, description="Filter by deployment status (e.g., RUNNING, FAILED)", alias="status"),
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
    
    Returns paginated results with total count.
    """
    
    # Build query: admins get all deployments, lecturers only their own
    # Note: Since we removed Course FK, we can't filter by lecturer anymore
    # We'll need to use openstack_project or another mechanism in the future
    query = db.query(Deployment)
    
    # Apply filters
    if course_id:
        query = query.filter(Deployment.course_id == str(course_id))
    
    if template_id:
        query = query.join(TemplateVersion).filter(TemplateVersion.template_id == template_id)
    
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
    
    # Get total count before pagination
    total = query.count()
    
    # Apply pagination
    deployments = (
        query
        .order_by(Deployment.created_at.desc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
        .all()
    )
    
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
    deployment = service.create_deployment(
        deployment_data,
        request_id=request_id
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
):
    """Get detailed information about a single deployment.
    
    Returns complete deployment details including:
    - Deployment metadata and configuration
    - Current status and timestamps
    - Associated template version and course
    - OpenStack Heat stack information (if available)
    - Deployment instances with access URLs
    
    **Authorization:** Owner (lecturer) or Admin only.
    
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
    
    # Check authorization: Lecturers can only see their own deployments
    # Note: Since we removed Course FK, authorization is simplified for now
    # Future: Check via openstack_project relationship
    
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
            "instance_name": instance.instance_name,
            "openstack_instance_id": instance.openstack_instance_id,
            "status": instance.status.value if instance.status else None,
            "ip_address": instance.ip_address,
            "access_urls": instance.access_urls_json,
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
    
    # Check authorization: Lecturers can only see their own deployments
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    
    if not is_admin:
        # Non-admin users can only access their own deployments
        owner_id = get_deployment_owner_id(deployment, db)
        if user["user_id"] != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this deployment"
            )
    
    # Get logs
    log_service = DeploymentLogService(db)
    logs = log_service.get_deployment_logs(deployment_id)
    
    return ResponseBuilder.success(
        data=[DeploymentLogResponse.model_validate(log) for log in logs],
        message=f"Retrieved {len(logs)} log entries for deployment",
        request_id=request_id
    )


@router.get("/{deployment_id}/credentials", response_model=dict)
async def get_deployment_credentials(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: CurrentUser,
):
    """Return generated user credentials for a deployment.

    Accessible to the lecturer who owns the deployment or any admin. Passwords
    are decrypted on read by the EncryptedString TypeDecorator on the model.
    """
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)
    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    if not is_admin:
        owner_id = get_deployment_owner_id(deployment, db)
        if user["user_id"] != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this deployment"
            )

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
                    access_type=access.access_type.value,
                    username=access.username,
                    password=access.password,
                    connection_url=access.connection_url,
                    port=access.port,
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


@router.get("/{deployment_id}/stack")
async def get_deployment_stack(
    deployment_id: str,
    db: DBSession,
    request_id: RequestID,
    user: dict = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER)),
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
    
    # Check authorization: Lecturers can only see their own deployments
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    
    if not is_admin:
        # Non-admin users can only access their own deployments
        owner_id = get_deployment_owner_id(deployment, db)
        if user["user_id"] != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this deployment"
            )
    
    if not deployment.openstack_stack_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Heat stack associated with this deployment"
        )
    
    # Get deployment owner's OpenStack project
    openstack_repo = OpenstackProjectRepository(db)
    owner_id = get_deployment_owner_id(deployment, db)
    openstack_projects = openstack_repo.get_by_owner(owner_id)
    
    if not openstack_projects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No OpenStack project found for owner {owner_id}"
        )
    
    openstack_project = openstack_projects[0]
    
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
    
    # Check authorization: Lecturers can only restart their own deployments
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]
    
    if not is_admin:
        owner_id = get_deployment_owner_id(deployment, db)
        if user["user_id"] != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to restart this deployment"
            )
    
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
):
    """Request deletion of a deployment.

    Sets deployment status to DELETING, logs the request and enqueues the
    `delete_deployment` Celery task which performs the actual OpenStack
    deletion and cleans up the database.
    """
    # Verify deployment exists
    deployment_repo = DeploymentRepository(db)
    deployment = deployment_repo.get_by_id(deployment_id)

    if not deployment:
        raise NotFoundException(f"Deployment with ID {deployment_id} not found")

    # Authorization: Lecturers may delete only their own deployments
    user_roles = user.get("roles", [])
    is_admin = "admin" in [role.lower() for role in user_roles]

    if not is_admin:
        owner_id = get_deployment_owner_id(deployment, db)
        if user["user_id"] != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this deployment",
            )

    # Enqueue Celery task to perform deletion asynchronously
    try:
        delete_deployment_task.delay(deployment_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue deletion task",
        )

    return ResponseBuilder.no_content(
        message="Deletion requested; operation is in progress",
        request_id=request_id,
    )
