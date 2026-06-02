"""Deploy tasks for Celery."""
import json
import logging
from uuid import UUID
from src.celery_app import celery_app
from src.core.database import SessionLocal
from src.models.deployment import DeploymentStatus
from src.models.deployment_log import DeploymentLogLevel, DeploymentLogEventType
from src.models.template_version_file import FileType
from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.deployment_log_repository import DeploymentLogRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.services.template_version_file_service import TemplateVersionFileService
from src.services.deployment_log_service import DeploymentLogService
from src.services.deployment_credential_service import DeploymentCredentialService
from src.services.openstack_heat_service import HeatStackService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def deploy_stack(self, deployment_id: str) -> dict:
    """Deploy Heat stacks asynchronously for a deployment.
    
    Orchestrates OpenStack Heat stack creation for a deployment.
    Creates ONE Heat stack per stack_assignment with its own user_json.
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
                "keycloak_group_id": deployment.course_id
            }
        )
        
        # Update status to CREATING
        repo.update_status(deployment_id, DeploymentStatus.CREATING)
        logger.info(f"Deployment {deployment_id} status updated to CREATING")
        
        # Parse deployment_parameters to get stack_assignments, teacher, and template name
        if not deployment.deployment_parameters:
            error_msg = "No deployment_parameters found in deployment"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        try:
            deployment_params = json.loads(deployment.deployment_parameters)
            template_name = deployment_params.get("template_name", "unknown")
            base_heat_parameters = deployment_params.get("heat_parameters", {})
            stack_assignments = deployment_params.get("stack_assignments", [])
            teacher_info = deployment_params.get("teacher", {})
            
            if not stack_assignments:
                error_msg = "No stack_assignments found in deployment_parameters"
                logger.error(error_msg)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=error_msg,
                    level=DeploymentLogLevel.ERROR
                )
                repo.update_status(deployment_id, DeploymentStatus.FAILED)
                return {"status": "failed", "error": error_msg}
            
            logger.info(f"Found {len(stack_assignments)} stack assignments to deploy")
            
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
        
        # Fetch template version files ONCE (used for all stacks)
        logger.info(f"Fetching template files for version {deployment.template_version_id}")
        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Fetching template files for version {deployment.template_version_id}",
            level=DeploymentLogLevel.INFO
        )
        
        files = file_service.get_version_files(
            deployment.template_version_id,
            include_content=True,
            skip_access_check=True
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
        if not heat_file or not heat_file.content:
            error_msg = "No primary Heat template found or template has no content"
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
        
        logger.info(f"Found Heat template: {heat_file.file_name} ({len(heat_file.content)} bytes)")
        
        # Get lecturer OpenStack project
        teacher_keycloak_id = teacher_info.get("id")
        if not teacher_keycloak_id:
            error_msg = "No teacher information found in deployment parameters"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        # Map Keycloak ID to local user ID
        from src.models.user import User
        lecturer_user = db.query(User).filter(User.external_id == teacher_keycloak_id).first()
        
        if not lecturer_user:
            error_msg = f"No user found for Keycloak ID {teacher_keycloak_id}"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        lecturer_id = lecturer_user.id
        
        # Get lecturer's OpenStack project
        openstack_repo = OpenstackProjectRepository(db)
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
        logger.info(f"Using OpenStack project {openstack_project.openstack_project_name} for lecturer {lecturer_id}")
        
        # Initialize Heat service ONCE
        heat_service = HeatStackService(openstack_project)
        
        # Prepare cloud-init files dictionary (same for all stacks)
        files_dict = {}
        for template_file in files:
            if template_file.file_type == FileType.CLOUD_INIT and template_file.content:
                files_dict['../cloud-init/user-data.yaml'] = template_file.content
                logger.info("Including cloud-init file in stack files")
        
        # Create ONE Heat stack per stack_assignment
        created_stack_ids = []
        failed_stacks = []
        
        from src.services.template_user_management_service import TemplateUserManagementService
        from src.schemas.deployment import StackAssignment, TeacherInfo
        
        for idx, stack_assignment_data in enumerate(stack_assignments, start=1):
            try:
                # Reconstruct Pydantic objects from JSON
                stack_assignment = StackAssignment(**stack_assignment_data)
                teacher = TeacherInfo(**teacher_info)
                
                # Generate user_json for THIS specific stack
                # Pass pw_min_length from heat_parameters so generated passwords
                # satisfy the per-deployment pwquality policy that cloud-init enforces
                # via PAM (chpasswd would otherwise reject overly short passwords).
                min_pw = int(base_heat_parameters.get("pw_min_length", 12))
                user_json_data = TemplateUserManagementService.generate_user_json_for_stack(
                    template_name=template_name,
                    course_label=deployment.name,
                    stack_assignment=stack_assignment,
                    teacher=teacher,
                    min_password_length=min_pw,
                )

                # Base64-encode JSON to avoid YAML parsing issues when inserted via str_replace
                # Cloud-init will decode it back to JSON
                import base64
                user_json_string = json.dumps(user_json_data, ensure_ascii=False)
                user_json_b64 = base64.b64encode(user_json_string.encode('utf-8')).decode('ascii')
                logger.debug(f"Generated user_json for stack {idx}: {len(user_json_string)} chars, {len(user_json_b64)} chars base64")
                
                # Merge base parameters with stack-specific user_json (base64-encoded)
                stack_params = {
                    **base_heat_parameters,
                    "user_json": user_json_b64
                }
                
                # Generate unique stack name
                stack_name = f"{deployment.name}-s{idx}-{deployment_id[:4]}"
                stack_name = stack_name.replace(" ", "-").replace("_", "-").lower()[:64]
                
                tags = {
                    "deployment_id": deployment_id,
                    "course_id": deployment.course_id,
                    "template_version_id": deployment.template_version_id,
                    "stack_index": str(idx)
                }
                
                logger.info(f"Creating Heat stack {idx}/{len(stack_assignments)}: {stack_name}")
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                    message=f"Creating Heat stack {idx}/{len(stack_assignments)}: {stack_name}",
                    level=DeploymentLogLevel.INFO,
                    details={
                        "stack_index": idx,
                        "stack_name": stack_name,
                        "groups_count": len(stack_assignment.groups),
                        "parameters": list(stack_params.keys())
                    }
                )
                
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
                created_stack_ids.append(stack_id)
                logger.info(f"Heat stack {idx} created successfully: {stack_id}")
                
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.STACK_CREATE,
                    message=f"Heat stack {idx} created: {stack_name}",
                    level=DeploymentLogLevel.INFO,
                    details={
                        "stack_id": stack_id,
                        "stack_name": stack_name,
                        "stack_index": idx,
                        "status": stack_result['status'],
                    }
                )

                try:
                    DeploymentCredentialService(db).persist_credentials_for_stack(
                        deployment_id=deployment_id,
                        stack_name=stack_name,
                        openstack_stack_id=stack_id,
                        user_json=user_json_data,
                    )
                except Exception as cred_error:
                    # Best-effort: a failure to record credentials must not roll back the
                    # stack itself. Surface the error in the deployment log so the lecturer
                    # knows credentials need to be retrieved another way.
                    logger.error(f"Failed to persist credentials for stack {idx}: {cred_error}", exc_info=True)
                    log_service.log(
                        deployment_id=deployment_id,
                        event_type=DeploymentLogEventType.FAILED,
                        message=f"Stack {idx} created but credential persistence failed",
                        level=DeploymentLogLevel.ERROR,
                        details={"stack_index": idx, "error": str(cred_error)}
                    )
                
            except Exception as stack_error:
                error_msg = f"Failed to create Heat stack {idx}: {str(stack_error)}"
                logger.error(error_msg, exc_info=True)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=error_msg,
                    level=DeploymentLogLevel.ERROR,
                    details={"error": str(stack_error), "stack_index": idx}
                )
                failed_stacks.append({"index": idx, "error": str(stack_error)})
        
        # Store all stack IDs as JSON array
        if created_stack_ids:
            deployment.openstack_stack_id = json.dumps(created_stack_ids)
            db.commit()
            logger.info(f"Stored {len(created_stack_ids)} stack IDs: {created_stack_ids}")
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.VM_READY,
                message=f"Created {len(created_stack_ids)}/{len(stack_assignments)} Heat stacks",
                level=DeploymentLogLevel.INFO,
                details={
                    "stack_ids": created_stack_ids,
                    "total_stacks": len(stack_assignments),
                    "failed_stacks": len(failed_stacks)
                }
            )
        
        # Update deployment status based on results
        if failed_stacks and not created_stack_ids:
            # All stacks failed
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {
                "status": "failed",
                "error": f"All {len(failed_stacks)} stacks failed",
                "failed_stacks": failed_stacks
            }
        elif failed_stacks:
            # Partial failure
            logger.warning(f"Partial deployment success: {len(created_stack_ids)} succeeded, {len(failed_stacks)} failed")
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)
            return {
                "status": "partial",
                "created_stacks": len(created_stack_ids),
                "failed_stacks": failed_stacks
            }
        else:
            # All stacks succeeded
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)
            logger.info(f"All {len(created_stack_ids)} stacks created successfully")
            return {
                "status": "success",
                "stack_count": len(created_stack_ids),
                "stack_ids": created_stack_ids
            }
        
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
                event_type=DeploymentLogEventType.STACK_CREATE,
                message=f"Heat stack created: {stack_name}",
                level=DeploymentLogLevel.INFO,
                details={
                    "stack_id": stack_id,
                    "stack_index": idx,
                    "status": stack_result['status'],
                }
            )
                
        except Exception as stack_error:
            error_msg = f"Failed to create Heat stack {idx}: {str(stack_error)}"
            logger.error(error_msg, exc_info=True)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR,
                details={"error": str(stack_error), "stack_index": idx}
            )
            failed_stacks.append({"index": idx, "error": str(stack_error)})
        
        # Store all stack IDs as JSON array
        if created_stack_ids:
            deployment.openstack_stack_id = json.dumps(created_stack_ids)
            db.commit()
            logger.info(f"Stored {len(created_stack_ids)} stack IDs: {created_stack_ids}")
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.VM_READY,
                message=f"Created {len(created_stack_ids)}/{len(stack_assignments)} Heat stacks",
                level=DeploymentLogLevel.INFO,
                details={
                    "stack_ids": created_stack_ids,
                    "total_stacks": len(stack_assignments),
                    "failed_stacks": len(failed_stacks)
                }
            )
        
        # Update deployment status based on results
        if failed_stacks and not created_stack_ids:
            # All stacks failed
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {
                "status": "failed",
                "error": f"All {len(failed_stacks)} stacks failed",
                "failed_stacks": failed_stacks
            }
        elif failed_stacks:
            # Partial failure
            logger.warning(f"Partial deployment success: {len(created_stack_ids)} succeeded, {len(failed_stacks)} failed")
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)
            return {
                "status": "partial",
                "created_stacks": len(created_stack_ids),
                "failed_stacks": failed_stacks
            }
        else:
            # All stacks succeeded
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)
            logger.info(f"All {len(created_stack_ids)} stacks created successfully")
            return {
                "status": "success",
                "stack_count": len(created_stack_ids),
                "stack_ids": created_stack_ids
            }
    
    except Exception as e:
        logger.exception(f"Failed to deploy stacks for deployment {deployment_id}: {e}")
        
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
                # Extract owner ID from deployment_parameters
                if not deployment.deployment_parameters:
                    raise ValueError("Deployment parameters are missing")
                params = json.loads(deployment.deployment_parameters)
                teacher_info = params.get("teacher", {})
                teacher_keycloak_id = teacher_info.get("id")
                
                if not teacher_keycloak_id:
                    logger.warning("No teacher information in deployment_parameters; skipping stack deletion")
                else:
                    # Map Keycloak ID to local user ID
                    from src.models.user import User
                    teacher_user = db.query(User).filter(User.external_id == teacher_keycloak_id).first()
                    
                    if not teacher_user:
                        logger.warning(f"Teacher user not found for Keycloak ID {teacher_keycloak_id}; skipping stack deletion")
                    else:
                        openstack_repo = OpenstackProjectRepository(db)
                        openstack_projects = openstack_repo.get_by_owner(teacher_user.id)

                        if openstack_projects:
                            heat_service = HeatStackService(openstack_projects[0])
                            
                            # Parse stack IDs (can be single ID or JSON array)
                            try:
                                stack_ids = json.loads(deployment.openstack_stack_id)
                                if not isinstance(stack_ids, list):
                                    stack_ids = [stack_ids]
                            except (json.JSONDecodeError, TypeError):
                                # Fallback: treat as single stack ID
                                stack_ids = [deployment.openstack_stack_id]
                            
                            logger.info(f"Deleting {len(stack_ids)} Heat stack(s)")
                            deleted_count = 0
                            failed_deletions = []
                            
                            for idx, stack_id in enumerate(stack_ids, start=1):
                                try:
                                    heat_service.delete_stack(stack_id)
                                    deleted_count += 1
                                    logger.info(f"Heat stack {idx}/{len(stack_ids)} deleted: {stack_id}")
                                except Exception as delete_error:
                                    logger.error(f"Failed to delete stack {stack_id}: {delete_error}")
                                    failed_deletions.append({"stack_id": stack_id, "error": str(delete_error)})
                            
                            log_service.log(
                                deployment_id=deployment_id,
                                event_type=DeploymentLogEventType.DEPLOYMENT_DELETED,
                                message=f"Heat stacks deleted: {deleted_count}/{len(stack_ids)} succeeded",
                                level=DeploymentLogLevel.INFO if not failed_deletions else DeploymentLogLevel.WARNING,
                                details={
                                    "deleted_count": deleted_count,
                                    "total_stacks": len(stack_ids),
                                    "failed_deletions": failed_deletions if failed_deletions else None
                                }
                            )
                        else:
                            logger.warning(f"No OpenStack project found for teacher {teacher_user.id}; skipping stack deletion")
            except Exception as e:
                logger.error(f"Failed to delete Heat stacks: {e}", exc_info=True)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.FAILED,
                    message=f"Failed to delete Heat stacks: {str(e)}",
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
        
        # Get OpenStack project credentials from deployment owner
        if not deployment.deployment_parameters:
            error_msg = "Deployment parameters are missing"
            logger.error(f"[{deployment_id}] {error_msg}")
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        params = json.loads(deployment.deployment_parameters)
        teacher_info = params.get("teacher", {})
        teacher_keycloak_id = teacher_info.get("id")
        
        if not teacher_keycloak_id:
            error_msg = "No teacher information found in deployment parameters"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        # Map Keycloak ID to local user ID
        from src.models.user import User
        teacher_user = db.query(User).filter(User.external_id == teacher_keycloak_id).first()
        
        if not teacher_user:
            error_msg = f"Teacher user not found for Keycloak ID {teacher_keycloak_id}"
            logger.error(error_msg)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=error_msg,
                level=DeploymentLogLevel.ERROR
            )
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": error_msg}
        
        openstack_repo = OpenstackProjectRepository(db)
        openstack_projects = openstack_repo.get_by_owner(teacher_user.id)
        
        if not openstack_projects:
            error_msg = f"No OpenStack project found for teacher {teacher_user.id}"
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
