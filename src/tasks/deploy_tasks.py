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
from src.services.template_version_file_service import TemplateVersionFileService
from src.services.deployment_log_service import DeploymentLogService
from src.services.deployment_credential_service import DeploymentCredentialService
from src.services.openstack_heat_service import HeatStackService
from src.services.ansible_service import AnsibleService
from src.services.credential_generator_service import CredentialGeneratorService
from src.utils.app_manifest_parser import AppManifestParser
from src.core.config import get_settings

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def deploy_stack(self, deployment_id: str) -> dict:
    """Deploy Heat stacks and run Ansible playbooks for a deployment.

    Flow per stack_assignment:
      1. Create Heat stack
      2. Wait for SSH
      3. Copy scripts/ and files/ to VM
      4. Run playbooks/ in order with generated credentials as extra-vars
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

        log_service.log(
            deployment_id=deployment_id,
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Deployment task started (task_id: {task_id})",
            level=DeploymentLogLevel.INFO,
            details={"task_id": task_id, "template_version_id": deployment.template_version_id},
        )
        repo.update_status(deployment_id, DeploymentStatus.CREATING)

        # --- Parse deployment parameters ---
        if not deployment.deployment_parameters:
            return _fail(repo, log_service, deployment_id, "No deployment_parameters found")

        try:
            deployment_params = json.loads(deployment.deployment_parameters)
            all_parameters = deployment_params.get("parameters", {})
            stack_assignments_raw = deployment_params.get("stack_assignments", [])
            teacher_info = deployment_params.get("teacher", {})
        except json.JSONDecodeError as e:
            return _fail(repo, log_service, deployment_id, f"Invalid deployment_parameters JSON: {e}")

        if not stack_assignments_raw:
            return _fail(repo, log_service, deployment_id, "No stack_assignments found")

        # --- Load template files from DB ---
        files = file_service.get_version_files(
            deployment.template_version_id, include_content=True, skip_access_check=True
        )
        if not files:
            return _fail(repo, log_service, deployment_id, f"No files found for template version {deployment.template_version_id}")

        heat_file = next((f for f in files if f.is_primary), None)
        if not heat_file or not heat_file.content:
            return _fail(repo, log_service, deployment_id, "No primary Heat template found")

        # Split parameters: Heat gets only what heat/main.yaml defines, Ansible gets the rest
        import yaml as _yaml
        try:
            heat_template_parsed = _yaml.safe_load(heat_file.content)
            heat_defined_params = set(heat_template_parsed.get("parameters", {}).keys())
        except Exception:
            heat_defined_params = set()

        backend_managed = {"user_json", "key_name"}
        base_heat_parameters = {
            k: v for k, v in all_parameters.items()
            if k in heat_defined_params and k not in backend_managed
        }
        ansible_parameters = {
            k: v for k, v in all_parameters.items()
            if k not in heat_defined_params
        }

        # Parse app.yaml for credentials spec and playbook list
        app_yaml_file = next((f for f in files if f.file_name == "app.yaml"), None)
        credentials_spec: dict[str, list] = {"per_student": [], "teacher": []}
        playbooks: list[tuple[str, str]] = []
        scripts: dict[str, str] = {}
        template_files: dict[str, str] = {}

        if app_yaml_file and app_yaml_file.content:
            manifest = AppManifestParser.parse(app_yaml_file.content)
            credentials_spec = manifest.get("credentials", credentials_spec)

        # Load _common playbooks first (sorted by filename → 00_, 01_, ...)
        from pathlib import Path
        common_playbooks_dir = Path(__file__).parent.parent / "_common" / "playbooks"
        if common_playbooks_dir.exists():
            for common_file in sorted(common_playbooks_dir.glob("*.yml")):
                playbooks.append((f"_common/{common_file.name}", common_file.read_text()))

        # Then template-specific playbooks
        for f in sorted(files, key=lambda x: (x.order, x.file_name)):
            if f.file_type == FileType.ANSIBLE_PLAYBOOK and f.content:
                playbooks.append((f.file_name, f.content))
            elif f.file_type == FileType.SHELL_SCRIPT and f.content:
                scripts[f.file_name] = f.content
            elif f.file_type == FileType.CONFIG_FILE and f.content:
                template_files[f.file_name] = f.content

        # --- Get OpenStack credentials ---
        # The OpenStack project this deployment runs against is now persisted
        # on the deployment row itself (FK), so we no longer have to derive it
        # from teacher.id and pick the first of the user's projects (which was
        # wrong whenever a user had more than one OpenstackProject row).
        openstack_project = deployment.openstack_project
        if not openstack_project:
            return _fail(
                repo, log_service, deployment_id,
                f"Deployment {deployment_id} has no openstack_project_id set",
            )

        heat_service = HeatStackService(openstack_project)

        # Ensure the Ansible keypair exists in OpenStack before creating stacks
        if get_settings().ansible_ssh_private_key:
            try:
                from src.services.ansible_keypair_service import AnsibleKeypairService
                AnsibleKeypairService.ensure_keypair(openstack_project)
            except Exception as kp_err:
                return _fail(repo, log_service, deployment_id, f"Failed to ensure Ansible keypair: {kp_err}")

        # SSH private key from settings (shared backend key, not per-project)
        ssh_private_key = get_settings().ansible_ssh_private_key or ""

        # cloud-init files dict for Heat
        files_dict = {}
        for f in files:
            if f.file_type == FileType.CLOUD_INIT and f.content:
                files_dict["../cloud-init/user-data.yaml"] = f.content

        # Reconstruct Pydantic objects
        from src.schemas.deployment import StackAssignment, TeacherInfo
        teacher = TeacherInfo(**teacher_info)

        created_stack_ids = []
        failed_stacks = []

        for idx, stack_assignment_data in enumerate(stack_assignments_raw, start=1):
            stack_id = None  # set after Heat succeeds
            try:
                stack_assignment = StackAssignment(**stack_assignment_data)

                # --- Generate credentials from app.yaml spec ---
                generated = CredentialGeneratorService.generate(
                    credentials_spec=credentials_spec,
                    stack_assignment=stack_assignment,
                    teacher=teacher,
                )

                stack_params = {**base_heat_parameters}
                stack_params["key_name"] = get_settings().ansible_ssh_key_name
                stack_name = f"{deployment.name}-s{idx}-{deployment_id[:4]}"
                stack_name = stack_name.replace(" ", "-").replace("_", "-").lower()[:64]
                tags = {
                    "deployment_id": deployment_id,
                    "course_id": deployment.course_id,
                    "template_version_id": deployment.template_version_id,
                    "stack_index": str(idx),
                }

                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
                    message=f"Creating Heat stack {idx}/{len(stack_assignments_raw)}: {stack_name}",
                    level=DeploymentLogLevel.INFO,
                    details={"stack_index": idx, "stack_name": stack_name},
                )

                # --- 1. Create Heat stack ---
                stack_result = heat_service.create_stack(
                    stack_name=stack_name,
                    template=heat_file.content,
                    parameters=stack_params,
                    files=files_dict or None,
                    tags=tags,
                    timeout_mins=60,
                )
                stack_id = stack_result["stack_id"]
                created_stack_ids.append(stack_id)

                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.STACK_CREATE,
                    message=f"Heat stack {idx} created: {stack_name}",
                    level=DeploymentLogLevel.INFO,
                    details={"stack_id": stack_id, "stack_name": stack_name, "stack_index": idx},
                )

                try:
                    # Build user_json from `generated` so DB passwords match what Ansible sets
                    credentials_for_db = {
                        "instance": {
                            "credentials": [
                                {
                                    "username": s["linux"]["username"],
                                    "password": s["linux"]["password"],
                                }
                                for s in generated.get("students", [])
                                if s.get("linux", {}).get("password")
                            ],
                            "admin_credentials": {
                                "username": generated["teacher"]["linux"]["username"],
                                "password": generated["teacher"]["linux"]["password"],
                            } if generated.get("teacher", {}).get("linux", {}).get("password") else None,
                        },
                    }
                    DeploymentCredentialService(db).persist_credentials_for_stack(
                        deployment_id=deployment_id,
                        stack_name=stack_name,
                        openstack_stack_id=stack_id,
                        user_json=credentials_for_db,
                        floating_ip=stack_result.get("floating_ip") or "",
                        heat_outputs=stack_result.get("outputs") or {},
                        flavor=stack_params.get("flavor"),
                    )
                except Exception as cred_error:
                    logger.error(f"Failed to persist credentials for stack {idx}: {cred_error}", exc_info=True)
                    log_service.log(
                        deployment_id=deployment_id,
                        event_type=DeploymentLogEventType.FAILED,
                        message=f"Stack {idx} created but credential persistence failed",
                        level=DeploymentLogLevel.ERROR,
                        details={"stack_index": idx, "error": str(cred_error)}
                    )

                # --- 2+3+4. Ansible (only if playbooks exist and SSH key available) ---
                if playbooks and ssh_private_key:
                    floating_ip = stack_result.get("floating_ip", "")
                    if not floating_ip:
                        log_service.log(
                            deployment_id=deployment_id,
                            event_type=DeploymentLogEventType.ANSIBLE_FAILED,
                            message=f"No floating_ip in stack result for stack {idx} — skipping Ansible",
                            level=DeploymentLogLevel.WARNING,
                        )
                    else:
                        ansible = AnsibleService(
                            db=db,
                            deployment_id=deployment_id,
                            floating_ip=floating_ip,
                            ssh_private_key=ssh_private_key,
                        )
                        ansible.wait_for_ssh()
                        ansible.copy_files(scripts=scripts, files=template_files)

                        extra_vars = {
                            **generated,
                            **ansible_parameters,
                            "course_label": deployment.name,
                            "stack_label": stack_name,
                            "ssh_allow_users": [
                                s["linux"]["username"]
                                for s in generated.get("students", [])
                                if s.get("linux", {}).get("password")
                            ],
                        }
                        ansible.run_playbooks(playbooks=playbooks, extra_vars=extra_vars)
                elif playbooks and not ssh_private_key:
                    log_service.log(
                        deployment_id=deployment_id,
                        event_type=DeploymentLogEventType.ANSIBLE_FAILED,
                        message="Playbooks defined but no SSH private key configured — skipping Ansible",
                        level=DeploymentLogLevel.WARNING,
                    )
            except Exception as stack_error:
                error_msg = f"Failed to deploy stack {idx}: {str(stack_error)}"
                logger.error(error_msg, exc_info=True)
                log_service.log(
                    deployment_id=deployment_id,
                    event_type=DeploymentLogEventType.ANSIBLE_FAILED if stack_id else DeploymentLogEventType.FAILED,
                    message=error_msg,
                    level=DeploymentLogLevel.ERROR,
                    details={"error": str(stack_error), "stack_index": idx},
                )
                failed_stacks.append({"index": idx, "error": str(stack_error)})

        # --- Store results ---
        if created_stack_ids:
            deployment.openstack_stack_id = json.dumps(created_stack_ids)
            db.commit()
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.VM_READY,
                message=f"Created {len(created_stack_ids)}/{len(stack_assignments_raw)} stacks",
                level=DeploymentLogLevel.INFO,
                details={"stack_ids": created_stack_ids, "failed_stacks": len(failed_stacks)},
            )

        if failed_stacks and not created_stack_ids:
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "error": f"All {len(failed_stacks)} stacks failed", "failed_stacks": failed_stacks}
        elif failed_stacks:
            # Some stacks failed (e.g. Ansible error) — mark as FAILED even if Heat succeeded
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
            return {"status": "failed", "created_stacks": len(created_stack_ids), "failed_stacks": failed_stacks}
        else:
            repo.update_status(deployment_id, DeploymentStatus.RUNNING)
            return {"status": "success", "stack_count": len(created_stack_ids), "stack_ids": created_stack_ids}

    except Exception as e:
        logger.exception(f"Failed to deploy stacks for deployment {deployment_id}: {e}")
        try:
            log_service = DeploymentLogService(db)
            log_service.log(
                deployment_id=deployment_id,
                event_type=DeploymentLogEventType.FAILED,
                message=f"Deployment failed: {str(e)}",
                level=DeploymentLogLevel.ERROR,
                details={"error": str(e), "error_type": type(e).__name__},
            )
        except Exception as log_error:
            logger.error(f"Failed to log deployment error: {log_error}")
        try:
            repo = DeploymentRepository(db)
            repo.update_status(deployment_id, DeploymentStatus.FAILED)
        except Exception:
            pass
        return {"status": "failed", "deployment_id": deployment_id, "error": str(e)}
    finally:
        db.close()


def _fail(repo, log_service, deployment_id: str, error_msg: str) -> dict:
    """Log error, set status to FAILED and return failure dict."""
    logger.error(error_msg)
    log_service.log(
        deployment_id=deployment_id,
        event_type=DeploymentLogEventType.FAILED,
        message=error_msg,
        level=DeploymentLogLevel.ERROR,
    )
    repo.update_status(deployment_id, DeploymentStatus.FAILED)
    return {"status": "failed", "error": error_msg}





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
                # The OpenStack project is now persisted on the deployment row
                # itself (FK), so deletion always targets the project the
                # deployment was actually created in — not just the user's
                # first OpenstackProject row.
                openstack_project = deployment.openstack_project

                if not openstack_project:
                    logger.warning(
                        f"Deployment {deployment_id} has no openstack_project_id set; "
                        "skipping stack deletion"
                    )
                else:
                    heat_service = HeatStackService(openstack_project)

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

        # Delete deployment_instances (FK prevents deleting deployment record otherwise)
        try:
            from src.models.deployment_instance import DeploymentInstance
            from src.models.deployment_instance_access import DeploymentInstanceAccess
            instances = db.query(DeploymentInstance).filter(
                DeploymentInstance.deployment_id == deployment_id
            ).all()
            for inst in instances:
                db.query(DeploymentInstanceAccess).filter(
                    DeploymentInstanceAccess.deployment_instance_id == inst.id
                ).delete(synchronize_session=False)
            db.query(DeploymentInstance).filter(
                DeploymentInstance.deployment_id == deployment_id
            ).delete(synchronize_session=False)
            db.commit()
            logger.info(f"Deleted {len(instances)} deployment instance(s) for {deployment_id}")
        except Exception as e:
            logger.warning(f"Failed to delete deployment instances for {deployment_id}: {e}")
            db.rollback()
        
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
        
        # Get OpenStack project from the deployment's persisted FK. Previously
        # this was re-derived from teacher.id at every read site and picked the
        # user's first OpenstackProject row, which broke whenever a user had
        # more than one (clouds.yaml switch scenario).
        openstack_project = deployment.openstack_project

        if not openstack_project:
            error_msg = f"Deployment {deployment_id} has no openstack_project_id set"
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
