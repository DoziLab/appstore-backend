"""Deploy tasks for Celery."""
import json
import logging
import secrets
import string
from uuid import UUID
from src.celery_app import celery_app
from src.core.database import SessionLocal
from src.models.deployment import DeploymentStatus, DeploymentMode
from src.models.deployment_log import DeploymentLogLevel, DeploymentLogEventType
from src.models.template_version_file import FileType
from src.models.course_member import CourseMember
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.deployment_log_repository import DeploymentLogRepository
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
        
        # Ensure content is not None
        if not heat_file.content:
            error_msg = f"Heat template {heat_file.file_name} has no content"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
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
        
        # Build Heat stack parameters from deployment_parameters (priority) or config_json (legacy)
        stack_params = {}
        
        if deployment.deployment_parameters:
            try:
                stack_params = json.loads(deployment.deployment_parameters)
                logger.info(f"Using Heat template parameters from deployment: {stack_params}")
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                    message="Heat template parameters loaded from deployment_parameters",
                    level=DeploymentLogLevel.INFO,
                    details={"parameters": stack_params}
                )
            except json.JSONDecodeError as e:
                error_msg = f"Invalid deployment_parameters JSON: {e}"
                logger.error(error_msg)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=error_msg,
                    level=DeploymentLogLevel.ERROR
                )
                repo.update_status(deployment_id, DeploymentStatus.FAILED)
                return {"status": "failed", "error": error_msg}
        elif deployment.config_json:
            try:
                config = json.loads(deployment.config_json)
                logger.info(f"Parsed deployment config (legacy): {config}")
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                    message="Deployment configuration parsed from config_json (legacy)",
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
        
        # Generate students parameter for per_course mode if not already provided
        if deployment.deployment_mode == DeploymentMode.PER_COURSE and "students" not in stack_params:
            logger.info("Generating students parameter for per_course deployment")
            
            # Get all course members (students) for this course
            course_members = (
                db.query(CourseMember)
                .filter(CourseMember.course_id == deployment.course_id)
                .filter(CourseMember.left_at.is_(None))  # Only active members
                .all()
            )
            
            if not course_members:
                error_msg = f"No active course members found for course {deployment.course_id}"
                logger.error(error_msg)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=error_msg,
                    level=DeploymentLogLevel.ERROR
                )
                repo.update_status(deployment_id, DeploymentStatus.FAILED)
                return {"status": "failed", "error": error_msg}
            
            # Generate students dict: username -> password
            # Use course_member_id as username base for uniqueness
            students_dict = {}
            
            def generate_password(length: int = 16) -> str:
                """Generate a secure random password."""
                alphabet = string.ascii_letters + string.digits + string.punctuation
                # Ensure at least one of each required type
                password = [
                    secrets.choice(string.ascii_lowercase),
                    secrets.choice(string.ascii_uppercase),
                    secrets.choice(string.digits)
                ]
                # Fill the rest randomly
                password.extend(secrets.choice(alphabet) for _ in range(length - 4))
                # Shuffle to avoid predictable pattern
                secrets.SystemRandom().shuffle(password)
                return ''.join(password)
            
            for member in course_members:
                # Generate username from course_member_id (first 8 chars for readability)
                username = f"student-{member.id[:8]}"
                # Generate secure password
                password = generate_password(16)
                students_dict[username] = password
            
            # Convert to JSON string as required by Heat template
            students_json = json.dumps(students_dict)
            stack_params["students"] = students_json
            
            logger.info(f"Generated students parameter for {len(course_members)} students")
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message=f"Generated students parameter for {len(course_members)} course members",
                level=DeploymentLogLevel.INFO,
                details={"student_count": len(course_members)}
            )
        
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
            
            # Prepare files dictionary for get_file references in template
            # Heat expects relative paths as used in get_file
            files_dict = {}
            for template_file in files:
                if template_file.file_type == FileType.CLOUD_INIT and template_file.content:
                    # Use path as referenced in template (e.g., ../cloud-init/user-data.yaml)
                    files_dict['../cloud-init/user-data.yaml'] = template_file.content
                    logger.info("Including cloud-init file in stack files")
            
            # Create stack via OpenStack Heat API
            stack_result = heat_service.create_stack(
                stack_name=stack_name,
                template=heat_file.content,
                parameters=stack_params,
                files=files_dict if files_dict else None,
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


@celery_app.task(bind=True)
def delete_deployment(self, deployment_id: str) -> dict:
    """Delete a deployment's OpenStack resources and remove DB record.

    This task performs the actual deletion on OpenStack and then deletes
    the deployment row from the database. It logs progress to the
    deployment logs table.
    """
    task_id = self.request.id
    logger.info(f"Starting delete task for deployment_id={deployment_id}, task_id={task_id}")

    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        log_service = DeploymentLogService(db)

        deployment = repo.get_by_id(deployment_id)
        if not deployment:
            logger.warning(f"Deployment not found for deletion: {deployment_id}")
            return {"status": "not_found", "deployment_id": deployment_id}

        # Update status to DELETING
        try:
            repo.update_status(deployment_id, DeploymentStatus.DELETING)
        except Exception:
            logger.warning("Could not set DELETING status; continuing with deletion")

        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_DELETION_REQUESTED,
            message=f"Deletion requested (task_id: {task_id})",
            level=DeploymentLogLevel.INFO,
            details={"task_id": task_id}
        )

        # If there is an associated Heat stack, attempt to delete it
        if deployment.openstack_stack_id:
            try:
                openstack_repo = OpenstackProjectRepository(db)
                lecturer_id = deployment.course.lecturer_id
                openstack_projects = openstack_repo.get_by_owner(lecturer_id)

                if openstack_projects:
                    heat_service = HeatStackService(openstack_projects[0])
                    heat_service.delete_stack(deployment.openstack_stack_id)
                    log_service.log(
                        deployment_id=deployment_id,
                        event_type=DeploymentLogEventType.DEPLOYMENT_DELETED,
                        message=f"Heat stack deleted: {deployment.openstack_stack_id}",
                        level=DeploymentLogLevel.INFO,
                        details={"stack_id": deployment.openstack_stack_id}
                    )
                else:
                    logger.warning(f"No OpenStack project found for lecturer {lecturer_id}; skipping stack deletion")
            except Exception as e:
                logger.error(f"Failed to delete Heat stack {deployment.openstack_stack_id}: {e}", exc_info=True)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=f"Failed to delete Heat stack: {str(e)}",
                    level=DeploymentLogLevel.ERROR,
                    details={"error": str(e)}
                )

        # Delete logs first (before deployment record)
        try:
            log_repo = DeploymentLogRepository(db)
            logs_deleted = log_repo.delete_by_deployment_id(deployment_id)
            logger.info(f"Deleted {logs_deleted} log entries for deployment {deployment_id}")
        except Exception as e:
            logger.warning(f"Failed to delete logs for deployment {deployment_id}: {e}")
        
        # Finally delete DB record
        try:
            deleted = repo.delete(UUID(deployment_id))
            if deleted:
                logger.info(f"Deployment record deleted from database: {deployment_id}")
            else:
                logger.warning(f"Deployment record not found when attempting delete: {deployment_id}")
        except Exception as e:
            logger.error(f"Failed to delete deployment record {deployment_id}: {e}", exc_info=True)

        return {"status": "deleted", "deployment_id": deployment_id, "task_id": task_id}

    except Exception as e:
        logger.exception(f"Error during delete task for deployment {deployment_id}: {e}")
        return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True)
def restart_deployment(self, deployment_id: str) -> dict:
    """Restart a deployment by updating the Heat stack.
    
    This task restarts an existing deployment by triggering a Heat stack update,
    which can restart VMs or refresh the stack configuration.
    
    Args:
        deployment_id: ID of the deployment to restart
        
    Returns:
        Result dictionary with status and task information
    """
    task_id = self.request.id
    logger.info(f"Starting restart task for deployment_id={deployment_id}, task_id={task_id}")
    
    db = SessionLocal()
    try:
        repo = DeploymentRepository(db)
        log_service = DeploymentLogService(db)
        
        deployment = repo.get_by_id(deployment_id)
        
        if not deployment:
            logger.error(f"Deployment not found: {deployment_id}")
            return {"status": "failed", "error": "Deployment not found"}
        
        # Update status to RESTARTING
        repo.update_status(deployment_id, DeploymentStatus.RESTARTING)
        
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Restart requested (task_id: {task_id})",
            level=DeploymentLogLevel.INFO,
            details={"task_id": task_id}
        )
        
        # Verify deployment has a stack
        if not deployment.openstack_stack_id:
            error_msg = "No OpenStack stack associated with this deployment"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        # Get OpenStack project credentials
        openstack_repo = OpenstackProjectRepository(db)
        lecturer_id = deployment.course.lecturer_id
        openstack_projects = openstack_repo.get_by_owner(lecturer_id)
        
        if not openstack_projects:
            error_msg = f"No OpenStack project found for lecturer {lecturer_id}"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        openstack_project = openstack_projects[0]
        
        try:
            heat_service = HeatStackService(openstack_project)
            
            # Trigger stack update to restart resources
            logger.info(f"Updating Heat stack {deployment.openstack_stack_id} to trigger restart")
            heat_service.update_stack(deployment.openstack_stack_id)
            
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message=f"Heat stack update initiated for restart: {deployment.openstack_stack_id}",
                level=DeploymentLogLevel.INFO,
                details={"stack_id": deployment.openstack_stack_id}
            )
            
            # Update status back to RUNNING (stack update is async in OpenStack)
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)
            
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                message="Restart completed successfully",
                level=DeploymentLogLevel.INFO
            )
            
            return {
                "status": "restarted",
                "deployment_id": deployment_id,
                "stack_id": deployment.openstack_stack_id,
                "task_id": task_id
            }
            
        except Exception as e:
            error_msg = f"Failed to restart deployment: {str(e)}"
            logger.exception(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR,
                details={"error": str(e)}
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}
            
    except Exception as e:
        logger.exception(f"Error during restart task for deployment {deployment_id}: {e}")
        return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}
    finally:
        db.close()
