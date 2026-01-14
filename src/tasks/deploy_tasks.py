"""Deploy tasks for Celery."""
import json
import logging
from src.celery_app import celery_app
from src.core.database import SessionLocal
from src.models.deployment import DeploymentStatus
from src.models.deployment_log import DeploymentLogLevel, DeploymentLogEventType
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.services.template_version_file_service import TemplateVersionFileService
from src.services.deployment_log_service import DeploymentLogService
from src.services.openstack_heat_service import HeatStackService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def deploy_stack(self, deployment_id: str) -> dict:
    """Deploy a Heat stack asynchronously.
    
    Orchestrates OpenStack Heat stack creation for a deployment.
    Updates deployment status throughout the process.
    
    Args:
        deployment_id: ID of the deployment to process
        
    Returns:
        Deployment result with status and task information
    """
    task_id = self.request.id
    logger.info(f"Starting deployment task for deployment_id={deployment_id}, task_id={task_id}")
    
    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        log_service = DeploymentLogService(db)
        file_service = TemplateVersionFileService(db)
        
        deployment = repo.get_by_id(deployment_id)
        
        if not deployment:
            logger.error(f"Deployment not found: {deployment_id}")
            return {"status": "failed", "error": "Deployment not found"}
        
        # Log: Deployment started
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Deployment task started (task_id: {task_id})",
            level=DeploymentLogLevel.INFO,
            details={
                "task_id": task_id,
                "template_version_id": deployment.template_version_id,
                "course_id": deployment.course_id,
                "deployment_mode": deployment.deployment_mode.value
            }
        )
        
        # Update status to CREATING
        repo.update_status(deployment_id, DeploymentStatus.CREATING)
        logger.info(f"Deployment {deployment_id} status updated to CREATING")
        
        # Fetch template version files
        logger.info(f"Fetching template files for version {deployment.template_version_id}")
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Fetching template files for version {deployment.template_version_id}",
            level=DeploymentLogLevel.INFO
        )
        
        files = file_service.get_version_files(
            deployment.template_version_id,
            include_content=True
        )
        
        if not files:
            error_msg = f"No files found for template version {deployment.template_version_id}"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        # Find primary Heat template
        heat_file = next((f for f in files if f.is_primary), None)
        if not heat_file:
            error_msg = "No primary Heat template found"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR,
                details={"available_files": [f.file_name for f in files]}
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        logger.info(f"Found Heat template: {heat_file.file_name} ({len(heat_file.content or '')} bytes)")
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.TEMPLATE_CREATE,
            message=f"Heat template loaded: {heat_file.file_name}",
            level=DeploymentLogLevel.INFO,
            details={
                "file_name": heat_file.file_name,
                "file_size": heat_file.file_size,
                "file_type": heat_file.file_type.value,
                "total_files": len(files)
            }
        )
        
        # Build Heat stack parameters from config_json
        stack_params = {}
        if deployment.config_json:
            try:
                config = json.loads(deployment.config_json)
                logger.info(f"Parsed deployment config: {config}")
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                    message="Deployment configuration parsed",
                    level=DeploymentLogLevel.INFO,
                    details=config
                )
                stack_params = config
            except json.JSONDecodeError as e:
                error_msg = f"Invalid config_json: {e}"
                logger.error(error_msg)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=error_msg,
                    level=DeploymentLogLevel.ERROR
                )
                repo.update_status(deployment_id, DeploymentStatus.FAILED)
                return {"status": "failed", "error": error_msg}
        
        # Get lecturer's OpenStack project from database
        openstack_repo = OpenstackProjectRepository(db)
        lecturer_id = deployment.course.lecturer_id
        
        # Get first OpenStack project for lecturer (in future: allow multiple projects)
        openstack_projects = openstack_repo.get_by_owner(lecturer_id)
        if not openstack_projects:
            error_msg = f"No OpenStack project found for lecturer {lecturer_id}"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR,
                details={"lecturer_id": lecturer_id}
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        openstack_project = openstack_projects[0]
        logger.info(
            f"Using OpenStack project {openstack_project.openstack_project_name} "
            f"for lecturer {lecturer_id}"
        )
        
        # Call OpenStack Heat API to create stack
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message="Initiating OpenStack Heat stack creation",
            level=DeploymentLogLevel.INFO,
            details={
                "template_file": heat_file.file_name,
                "parameters": stack_params,
                "openstack_project": openstack_project.openstack_project_name,
            }
        )
        
        try:
            heat_service = HeatStackService(openstack_project)
            
            # Generate stack name based on deployment
            stack_name = f"deployment-{deployment_id[:8]}-{deployment.course_id[:8]}"
            
            # Add deployment metadata as tags
            tags = {
                "deployment_id": deployment_id,
                "course_id": deployment.course_id,
                "template_version_id": deployment.template_version_id,
            }
            
            logger.info(f"Creating Heat stack: {stack_name}")
            
            # Create stack via OpenStack Heat API
            stack_result = heat_service.create_stack(
                stack_name=stack_name,
                template=heat_file.content,
                parameters=stack_params,
                tags=tags,
                timeout_mins=60
            )
            
            stack_id = stack_result['stack_id']
            logger.info(f"Heat stack created successfully: {stack_id}")
            
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.TEMPLATE_CREATE,
                message=f"Heat stack created: {stack_name}",
                level=DeploymentLogLevel.INFO,
                details={
                    "stack_id": stack_id,
                    "stack_name": stack_name,
                    "status": stack_result['status'],
                }
            )
            
        except Exception as heat_error:
            error_msg = f"Failed to create Heat stack: {str(heat_error)}"
            logger.error(error_msg, exc_info=True)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR,
                details={"error": str(heat_error)}
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        # Store stack_id
        deployment.openstack_stack_id = stack_id
        db.commit()
        
        logger.info(f"Stack ID stored: {stack_id}")
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.VM_READY,
            message=f"Heat stack ID stored: {stack_id}",
            level=DeploymentLogLevel.INFO,
            details={
                "stack_id": stack_id,
                "template": heat_file.file_name
            }
        )
        
        # Create DeploymentInstance records from Heat stack resources
        try:
            logger.info(f"Fetching stack resources for {stack_id}")
            resources = heat_service.get_stack_resources(stack_id)
            
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message=f"Retrieved {len(resources)} resources from Heat stack",
                level=DeploymentLogLevel.INFO,
                details={"resource_count": len(resources), "resources": resources}
            )
            
            # TODO: Create DeploymentInstance records for each VM/server resource
            # This will require checking resource types and extracting access information
            logger.info(f"Found {len(resources)} stack resources. Instance creation pending implementation.")
            
        except Exception as resource_error:
            # Non-fatal: Log warning but continue
            logger.warning(f"Failed to fetch stack resources: {resource_error}")
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message=f"Could not fetch stack resources: {str(resource_error)}",
                level=DeploymentLogLevel.WARNING,
                details={"error": str(resource_error)}
            )
        
        # Update status to RUNNING
        repo.update_status(deployment_id, DeploymentStatus.RUNNING)
        logger.info(f"Deployment {deployment_id} completed successfully")
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.VM_READY,
            message="Deployment completed successfully",
            level=DeploymentLogLevel.INFO,
            details={
                "status": "RUNNING",
                "stack_id": stack_id
            }
        )
        
        return {
            "status": "success",
            "deployment_id": deployment_id,
            "task_id": task_id,
            "stack_id": stack_id,
            "files_processed": len(files)
        }
        
    except Exception as e:
        logger.exception(f"Failed to deploy stack for deployment {deployment_id}: {e}")
        
        # Log the failure
        try:
            log_service = DeploymentLogService(db)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=f"Deployment failed: {str(e)}",
                level=DeploymentLogLevel.ERROR,
                details={
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log deployment error: {log_error}")
        
        # Update status to FAILED
        if db:
            try:
                repo = DeploymentRepository(db)
                repo.update_status(deployment_id, DeploymentStatus.FAILED)
            except Exception as status_error:
                logger.error(f"Failed to update deployment status: {status_error}")
        
        return {
            "status": "failed",
            "deployment_id": deployment_id,
            "error": str(e)
        }
    finally:
        db.close()
