"""Deploy tasks for Celery."""
import json
import logging
import time
import yaml

import openstack
from openstack.exceptions import SDKException

from src.celery_app import celery_app
from src.core.config import get_settings
from src.core.database import SessionLocal
from src.models.deployment import DeploymentStatus
from src.models.deployment_instance import DeploymentInstance
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.template_content_repository import TemplateContentRepository

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(bind=True)
def deploy_stack(self, deployment_id: str) -> dict:
    """Deploy a Heat stack asynchronously.
    
    Orchestrates OpenStack Heat stack creation for a deployment.
    Updates deployment status throughout the process.
    User does not wait for completion - task runs fully async.
    
    Args:
        deployment_id: ID of the deployment to process
        
    Returns:
        Deployment result with status and task information
    """
    logger.info(f"Starting deployment task for deployment_id={deployment_id}, task_id={self.request.id}")
    
    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        deployment = repo.get_by_id(deployment_id)
        
        if not deployment:
            logger.error(f"Deployment not found: {deployment_id}")
            return {"status": "failed", "error": "Deployment not found"}
        
        # Update status to CREATING
        repo.update_status(deployment_id, DeploymentStatus.CREATING)
        logger.info(f"Deployment {deployment_id} status updated to CREATING")
        
        # Check for idempotency - if stack already exists, check its status
        if deployment.openstack_stack_id:
            logger.info(f"Deployment {deployment_id} already has stack_id {deployment.openstack_stack_id}, checking status")
            stack_status = _check_existing_stack(deployment.openstack_stack_id)
            if stack_status:
                logger.info(f"Existing stack {deployment.openstack_stack_id} found with status {stack_status}")
                _handle_stack_completion(db, deployment, stack_status)
                return {
                    "status": "completed",
                    "deployment_id": deployment_id,
                    "stack_id": deployment.openstack_stack_id,
                    "task_id": self.request.id
                }
        
        # 1. Fetch template content from DB
        config = json.loads(deployment.config_json) if deployment.config_json else {}
        template_id = config.get("_template_id")
        template_version = config.get("_template_version")
        
        if not template_id or not template_version:
            raise ValueError(f"Template ID and version not found in deployment config for deployment {deployment_id}")
        
        template_content_repo = TemplateContentRepository(db)
        template_content = template_content_repo.get_by_template_and_version(template_id, template_version)
        
        if not template_content:
            raise ValueError(f"Template content not found for template_id={template_id}, version={template_version}")
        
        # Use template content as string directly (do not parse to avoid date conversion issues)
        heat_template_string = template_content.content
        logger.info(f"Loaded Heat template for deployment {deployment_id} from template {template_id} version {template_version}")
        
        # 2. Build Heat stack parameters from config_json
        stack_params = _build_stack_parameters(deployment, config)
        
        # 3. Call OpenStack Heat API to create stack
        logger.info(f"Creating Heat stack for deployment {deployment_id}")
        logger.info(f"Stack parameters: {stack_params}")
        logger.info(f"Stack parameters types: {[(k, type(v).__name__) for k, v in stack_params.items()]}")
        
        stack = _create_heat_stack(
            stack_name=f"deployment-{deployment_id[:8]}",
            template=heat_template_string,
            parameters=stack_params
        )
        
        # 4. Store stack_id in deployment.openstack_stack_id
        repo.update_stack_id(deployment_id, stack.id)
        logger.info(f"Stack {stack.id} created for deployment {deployment_id}")
        
        # 5. Wait for stack completion asynchronously (user does not wait)
        logger.info(f"Waiting asynchronously for stack {stack.id} to complete (timeout: 600s)")
        stack_status = _wait_for_stack_completion(stack.id, timeout_seconds=600)
        logger.info(f"Stack {stack.id} reached status: {stack_status}")
        
        # 6. Create DeploymentInstance records and update status
        _handle_stack_completion(db, deployment, stack_status)
        
        return {
            "status": "completed",
            "deployment_id": deployment_id,
            "stack_id": stack.id,
            "stack_status": stack_status,
            "task_id": self.request.id
        }
        
    except Exception as e:
        logger.exception(f"Failed to deploy stack for deployment {deployment_id}: {e}")
        if db:
            repo = DeploymentRepository(db)
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
        return {
            "status": "failed",
            "deployment_id": deployment_id,
            "error": str(e)
        }
    finally:
        db.close()


def _get_openstack_connection():
    """Create OpenStack connection using SDK.
    
    Returns:
        OpenStack connection object
    """
    return openstack.connect(
        auth_url=settings.openstack_auth_url,
        project_name=settings.openstack_project_name,
        username=settings.openstack_username,
        password=settings.openstack_password,
        user_domain_name=settings.openstack_user_domain_name,
        project_domain_name=settings.openstack_project_domain_name,
        region_name=settings.openstack_region_name,
        identity_api_version=settings.openstack_identity_api_version,
    )


def _build_stack_parameters(deployment, config: dict) -> dict:
    """Build Heat stack parameters from deployment configuration.
    
    Args:
        deployment: Deployment model instance
        config: Parsed config dictionary
        
    Returns:
        Dictionary of stack parameters (all values converted to strings for JSON serialization)
    """
    # Remove internal metadata fields
    params = {k: v for k, v in config.items() if not k.startswith("_")}
    
    # Add default parameters
    if "vm_name" not in params:
        params["vm_name"] = f"vm-{deployment.id[:8]}"
    
    # Convert all values to strings to avoid JSON serialization issues
    # (Heat accepts string parameters and converts them internally)
    params_stringified = {k: str(v) for k, v in params.items()}
    
    return params_stringified


def _create_heat_stack(stack_name: str, template: str, parameters: dict):
    """Create Heat stack via OpenStack SDK.
    
    Args:
        stack_name: Name for the stack
        template: Heat template as YAML string
        parameters: Stack parameters
        
    Returns:
        Created stack object
        
    Raises:
        SDKException: If stack creation fails
    """
    try:
        conn = _get_openstack_connection()
        
        # Create stack with template string directly (no YAML conversion)
        stack = conn.orchestration.create_stack(
            name=stack_name,
            template=template,
            parameters=parameters
        )
        
        logger.info(f"Heat stack {stack.id} created with name {stack_name}")
        return stack
        
    except SDKException as e:
        logger.error(f"Failed to create Heat stack {stack_name}: {e}")
        raise


def _check_existing_stack(stack_id: str) -> str | None:
    """Check if a stack exists and return its status.
    
    Args:
        stack_id: OpenStack stack ID
        
    Returns:
        Stack status string or None if not found
    """
    try:
        conn = _get_openstack_connection()
        stack = conn.orchestration.get_stack(stack_id)
        if stack:
            return stack.status
        return None
    except SDKException:
        logger.warning(f"Stack {stack_id} not found or error checking status")
        return None


def _wait_for_stack_completion(stack_id: str, timeout_seconds: int = 600) -> str:
    """Wait for Heat stack to reach a terminal state.
    
    Args:
        stack_id: OpenStack stack ID
        timeout_seconds: Maximum time to wait
        
    Returns:
        Final stack status
        
    Raises:
        TimeoutError: If stack doesn't complete within timeout
    """
    conn = _get_openstack_connection()
    start_time = time.time()
    
    # Terminal states for Heat stacks
    terminal_states = {"CREATE_COMPLETE", "CREATE_FAILED", "DELETE_COMPLETE", "DELETE_FAILED"}
    
    while True:
        if time.time() - start_time > timeout_seconds:
            raise TimeoutError(f"Stack {stack_id} did not complete within {timeout_seconds} seconds")
        
        try:
            stack = conn.orchestration.get_stack(stack_id)
            status = stack.status
            
            logger.info(f"Stack {stack_id} status: {status}")
            
            if status in terminal_states:
                return status
            
            # Wait before next check
            time.sleep(10)
            
        except SDKException as e:
            logger.error(f"Error checking stack {stack_id} status: {e}")
            raise


def _handle_stack_completion(db, deployment, stack_status: str):
    """Handle stack completion by creating instances and updating status.
    
    Args:
        db: Database session
        deployment: Deployment model instance
        stack_status: Final stack status
    """
    repo = DeploymentRepository(db)
    
    if stack_status == "CREATE_COMPLETE":
        # Stack created successfully
        logger.info(f"Stack {deployment.openstack_stack_id} created successfully")
        
        # Create DeploymentInstance records from stack resources
        _create_deployment_instances(db, deployment)
        
        # Update deployment status to RUNNING
        repo.update_status(str(deployment.id), DeploymentStatus.RUNNING)
        
    else:
        # Stack creation failed
        logger.error(f"Stack {deployment.openstack_stack_id} creation failed with status {stack_status}")
        repo.update_status(str(deployment.id), DeploymentStatus.FAILED)


def _create_deployment_instances(db, deployment):
    """Create DeploymentInstance records from Heat stack resources.
    
    Args:
        db: Database session
        deployment: Deployment model instance
    """
    try:
        conn = _get_openstack_connection()
        stack = conn.orchestration.get_stack(deployment.openstack_stack_id)
        
        # Get stack resources (VMs created by Heat)
        resources = list(conn.orchestration.resources(stack))
        
        # Get stack outputs for IP addresses
        outputs = {output["output_key"]: output["output_value"] for output in stack.outputs or []}
        
        for resource in resources:
            if resource.resource_type == "OS::Nova::Server":
                # Create DeploymentInstance for each VM
                instance = DeploymentInstance(
                    deployment_id=str(deployment.id),
                    vm_name=resource.name,
                    openstack_server_id=resource.physical_resource_id,
                    ip_address=outputs.get("server_ip"),  # Get from stack outputs
                    status="running"
                )
                db.add(instance)
        
        db.commit()
        logger.info(f"Created {len(resources)} DeploymentInstance records for deployment {deployment.id}")
        
    except SDKException as e:
        logger.error(f"Failed to create deployment instances: {e}")
        # Don't raise - deployment is still considered successful
