import json
import logging
from typing import Optional, Union
from uuid import UUID
from sqlalchemy.orm import Session

from src.repositories.deployment_repository import DeploymentRepository
from src.repositories.openstack_project_repository import OpenstackProjectRepository
from src.services.deployment_log_service import DeploymentLogService
from src.services.openstack_heat_service import HeatStackService
from src.schemas.deployment import DeploymentCreate, StackAssignment
from src.models.course import Course
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.group_member import GroupMember
from src.models.user import User as UserModel
from src.models.deployment import Deployment, DeploymentStatus
from src.models.deployment_log import DeploymentLogEventType, DeploymentLogLevel
from src.models.template_version import TemplateVersion
from src.models.openstack_project import OpenstackProject
from src.core.exceptions import NotFoundException
from src.core.exceptions import BadRequestException
from src.core.exceptions import ForbiddenException
from src.services.template_version_file_service import TemplateVersionFileService
from src.tasks.deploy_tasks import deploy_stack
from src.utils.deployment_expiry import compute_expiry, compute_extension, utcnow


logger = logging.getLogger(__name__)


class DeploymentService:
    """Service for deployment business logic."""
    
    def __init__(self, db: Session):
        """Initialize DeploymentService with database session."""
        self.db = db
        self.deployment_repo = DeploymentRepository(db)
        self.openstack_repo = OpenstackProjectRepository(db)
        self.log_service = DeploymentLogService(db)
    
    def create_deployment(self, deployment_data: DeploymentCreate, request_id: Union[str, None] = None) -> Deployment:
        """Create a new deployment and trigger async deployment task.
        
        Args:
            deployment_data: Validated deployment creation data with stack_assignments and teacher
            request_id: Request ID for tracing
            
        Returns:
            Created Deployment with status set to QUEUED
            
        Raises:
            NotFoundException: If template_version_id does not exist, or app.yaml not found
            BadRequestException: If required heat_parameters are missing or have invalid types
        """
        # Validate template_version_id exists
        template_version = self.db.query(TemplateVersion).filter(
            TemplateVersion.id == deployment_data.template_version_id
        ).first()

        if not template_version:
            raise NotFoundException(
                f"Template version with ID '{deployment_data.template_version_id}' not found"
            )

        # Fetch parent template up front so we can:
        # (1) gate private templates to owner-only deploys,
        # (2) reuse it later for template-specific user_json generation.
        from src.models.template import Template, TemplateVisibility
        template = self.db.query(Template).filter(
            Template.id == template_version.template_id
        ).first()
        if not template:
            raise NotFoundException(
                f"Template not found for version {template_version.id}"
            )

        # Resolve caller's local user id from the Keycloak ID in the payload.
        # This is needed for both the private-template owner check below AND
        # the OpenStack-project ownership validation further down — so we do
        # the lookup once here and reuse `teacher_user`.
        teacher_user = self.db.query(UserModel).filter(
            UserModel.external_id == deployment_data.teacher.id
        ).first()
        if not teacher_user:
            raise NotFoundException(
                f"Teacher user not found for Keycloak ID {deployment_data.teacher.id}"
            )

        # Gate: private templates can only be deployed by their owner. Admins
        # and other lecturers cannot run private templates even if they
        # somehow obtained the template_version_id — that's the whole point of
        # "private". For public templates the visibility/approval system
        # already controls who sees the template at all, no extra gate here.
        if template.visibility != TemplateVisibility.PUBLIC and template.owner_id != teacher_user.id:
            raise ForbiddenException(
                "Only the template owner can deploy a private template version"
            )

        # Validate template parameters required by the template version
        template_file_service = TemplateVersionFileService(self.db)
        try:
            template_params_resp = template_file_service.get_template_parameters(
                str(template_version.id),
                skip_access_check=True
            )
            template_params_map = {p.name: p for p in template_params_resp.parameters}
        except NotFoundException:
            raise
        except Exception as e:
            raise BadRequestException(f"Failed to read template parameters: {e}")

        provided = deployment_data.parameters or {}

        # Backend always injects these — never required from the caller
        backend_managed = {"user_json", "admin_credentials", "key_name"}

        # Validate all required parameters from app.yaml are provided
        required_params = [
            p.name for p in template_params_resp.parameters
            if p.required and p.name not in backend_managed
        ]
        if required_params:
            missing = [p for p in required_params if p not in provided]
            if missing:
                raise BadRequestException(f"Missing required template parameters: {', '.join(missing)}")

        # Type validation for provided parameters
        type_errors = []
        for param_name, param_value in provided.items():
            if param_name not in template_params_map:
                continue
            expected_type = template_params_map[param_name].type.lower()
            if expected_type == "boolean":
                if not isinstance(param_value, bool):
                    type_errors.append(f"{param_name}: expected boolean, got {type(param_value).__name__}")
            elif expected_type in ["number", "int", "integer"]:
                if not isinstance(param_value, (int, float)):
                    type_errors.append(f"{param_name}: expected number, got {type(param_value).__name__}")
            elif expected_type == "string":
                if not isinstance(param_value, str):
                    type_errors.append(f"{param_name}: expected string, got {type(param_value).__name__}")
        if type_errors:
            raise BadRequestException(f"Type validation errors: {'; '.join(type_errors)}")

        # Get or create Course entry based on keycloak_course_id
        # The course_id from frontend is the Keycloak group ID
        keycloak_course_id = deployment_data.course_id

        course = self.db.query(Course).filter(
            Course.keycloak_course_id == keycloak_course_id
        ).first()

        if not course:
            # Auto-create course entry with deployment name as course name
            course = Course(
                name=deployment_data.name,
                keycloak_course_id=keycloak_course_id
            )
            self.db.add(course)
            self.db.flush()  # Get the ID without committing

        # Materialize the membership graph the wizard implied so students see
        # their deployments. The /api/v1/student/* read path inner-joins
        # CourseMember → GroupMember → CourseGroup → DeploymentInstanceAccess,
        # so every student in the payload must end up with rows in all three.
        # See appstore-backend#169.
        #
        # Done up-front (synchronously, before the Celery task fires) so that
        # by the time `persist_credentials` stamps `course_group_id` onto
        # `DeploymentInstanceAccess.group_id`, the CourseGroup row it points
        # at is guaranteed to exist. Also lets us write the resolved
        # `course_group_id` back into the `stack_assignments` payload that's
        # persisted in `deployment_parameters` — so the credential task sees
        # the FK regardless of whether the frontend bothered to send it.
        stack_assignments_for_storage = self._upsert_course_membership_graph(
            course=course,
            stack_assignments=deployment_data.stack_assignments,
        )

        # Validate the target OpenStack project: must belong to the teacher
        # submitting this request. ``teacher_user`` was already resolved
        # earlier (private-template gate); re-using it here avoids a second
        # round-trip to the users table.
        openstack_project = self.openstack_repo.get_by_id(
            deployment_data.openstack_project_id
        )
        if not openstack_project:
            raise NotFoundException(
                f"OpenStack project {deployment_data.openstack_project_id} not found"
            )
        if openstack_project.owner_user_id != teacher_user.id:
            raise BadRequestException(
                "OpenStack project does not belong to teacher"
            )

        # Store complete deployment info as JSON. The stack_assignments here
        # carry the *resolved* `course_group_id` for every group, regardless
        # of what the wizard sent — so the credential persistence task always
        # has a non-null FK to stamp onto `DeploymentInstanceAccess.group_id`.
        deployment_parameters = json.dumps({
            "template_name": template.name,
            "parameters": provided,
            "stack_assignments": stack_assignments_for_storage,
            "teacher": deployment_data.teacher.model_dump()
        })

        # Create deployment record with initial status QUEUED
        # Use course.id (DB ID) instead of keycloak_course_id
        # Compute expiry timestamps from runtime_months so the daily Beat
        # sweep knows when to delete and the UI knows when to start warning.
        now = utcnow()
        expires_at, expiry_warning_at = compute_expiry(now, deployment_data.runtime_months)

        deployment = self.deployment_repo.create(
            name=deployment_data.name,
            template_version_id=deployment_data.template_version_id,
            course_id=str(course.id),  # Use DB course ID, not Keycloak group ID
            openstack_project_id=openstack_project.id,
            status=DeploymentStatus.QUEUED,
            deployment_parameters=deployment_parameters,
            expires_at=expires_at,
            expiry_warning_at=expiry_warning_at,
        )
        
        # Create initial log entry
        self.log_service.log(
            deployment_id=str(deployment.id),
            event_type=DeploymentLogEventType.DEPLOYMENT_STARTED,
            message=f"Deployment request received for template version {deployment_data.template_version_id}",
            level=DeploymentLogLevel.INFO,
            details={
                "template_version_id": deployment_data.template_version_id,
                "course_id": deployment_data.course_id,
                "keycloak_group_id": deployment_data.course_id,
                "stack_count": len(deployment_data.stack_assignments),
                "total_groups": sum(len(sa.groups) for sa in deployment_data.stack_assignments),
                "has_parameters": bool(deployment_data.parameters),
                "runtime_months": deployment_data.runtime_months,
                "expires_at": expires_at.isoformat(),
            },
            request_id=request_id
        )
        
        # Trigger async Celery task for Heat stack orchestration
        deploy_stack.delay(str(deployment.id))

        return deployment

    def _upsert_course_membership_graph(
        self,
        course: Course,
        stack_assignments: list[StackAssignment],
    ) -> list[dict]:
        """Idempotently materialize CourseMember / CourseGroup / GroupMember
        rows for every student in the wizard payload.

        Without this the `/api/v1/student/*` read path returns an empty list
        because its inner join through CourseMember → GroupMember →
        CourseGroup finds no matches. See appstore-backend#169.

        The function also resolves a `course_group_id` for every group in the
        payload (creating the CourseGroup if needed, matching by
        ``(course_id, name)``) and returns a fresh list of stack_assignment
        dicts with that id stamped onto each ``GroupInfo.course_group_id``.
        That stamped list is what gets persisted in `deployment_parameters`,
        so the credential task downstream stamps a non-null FK regardless of
        what the frontend originally sent.

        Idempotent end-to-end: every lookup is by stable natural key
        (``users.external_id``, ``(course_id, name)``,
        ``(group_id, course_member_id)``) and re-running the same payload is
        a no-op.

        Best-effort by design: a failure here logs and falls back to the
        payload as-is. The deployment itself still goes through — the
        lecturer's flow is unaffected — but students for that subtree may
        not see their credentials until the row is created manually or the
        deploy is retried. A hard error would punish the lecturer for a
        state-bookkeeping problem they can't fix.
        """
        out: list[dict] = []
        # Savepoint so a failure in the membership graph rolls back ONLY the
        # rows added below, not the Course row the caller just flushed.
        savepoint = self.db.begin_nested()
        try:
            for stack in stack_assignments:
                stack_dict = stack.model_dump()
                for idx, group in enumerate(stack.groups):
                    course_group = self._get_or_create_course_group(
                        course_id=str(course.id),
                        name=group.group_name,
                        hint_id=group.course_group_id,
                    )
                    for student in group.students:
                        course_member = self._get_or_create_course_member(
                            course_id=str(course.id),
                            keycloak_user_id=student.id,
                        )
                        if course_member is None:
                            # User has never logged in → no `users` row yet.
                            # Skip silently: when the student first logs in
                            # the row will be created by UserSyncService but
                            # the membership graph won't backfill on its own.
                            # That's an existing gap; we don't widen it here.
                            continue
                        self._get_or_create_group_member(
                            group_id=course_group.id,
                            course_member_id=course_member.id,
                        )
                    # Stamp resolved id back onto the dict we'll persist so
                    # the credential task sees the FK even if the frontend
                    # sent null.
                    stack_dict["groups"][idx]["course_group_id"] = course_group.id
                out.append(stack_dict)
            savepoint.commit()
        except Exception as exc:
            # Don't fail the deployment — log and fall back to the raw payload.
            # Worst case: students don't see their credentials until a retry
            # or manual membership add. Same failure mode as before this fix.
            savepoint.rollback()
            logger.warning(
                "Failed to materialize course membership graph for course %s: %s",
                course.id,
                exc,
                exc_info=True,
            )
            return [sa.model_dump() for sa in stack_assignments]
        return out

    def _get_or_create_course_group(
        self,
        course_id: str,
        name: str,
        hint_id: Optional[str] = None,
    ) -> CourseGroup:
        """Idempotent CourseGroup upsert keyed on ``(course_id, name)``.

        If the frontend already sent a ``course_group_id`` that points to a
        row of THIS course, trust it (covers the case where the lecturer
        renamed a group in the UI before deploying — we don't want to
        spawn a duplicate). Otherwise match by name; create if missing.
        """
        if hint_id:
            existing = self.db.query(CourseGroup).filter(
                CourseGroup.id == hint_id,
                CourseGroup.course_id == course_id,
            ).first()
            if existing:
                return existing
        existing = self.db.query(CourseGroup).filter(
            CourseGroup.course_id == course_id,
            CourseGroup.name == name,
        ).first()
        if existing:
            return existing
        cg = CourseGroup(course_id=course_id, name=name)
        self.db.add(cg)
        self.db.flush()
        return cg

    def _get_or_create_course_member(
        self,
        course_id: str,
        keycloak_user_id: str,
    ) -> Optional[CourseMember]:
        """Idempotent CourseMember upsert keyed on ``(user_id, course_id)``.

        Returns None when the student has no `users` row yet — they've never
        logged in, so we can't FK to them. Surfaces as a debug log; the
        deployment still proceeds for the other students.
        """
        user = self.db.query(UserModel).filter(
            UserModel.external_id == keycloak_user_id
        ).first()
        if not user:
            logger.debug(
                "Skipping CourseMember upsert for unknown Keycloak user %s "
                "(no local users row — student has never logged in)",
                keycloak_user_id,
            )
            return None
        existing = self.db.query(CourseMember).filter(
            CourseMember.user_id == user.id,
            CourseMember.course_id == course_id,
        ).first()
        if existing:
            # Re-activate a soft-left member rather than creating a duplicate.
            if existing.left_at is not None:
                existing.left_at = None
                self.db.flush()
            return existing
        cm = CourseMember(user_id=user.id, course_id=course_id)
        self.db.add(cm)
        self.db.flush()
        return cm

    def _get_or_create_group_member(
        self,
        group_id: str,
        course_member_id: str,
    ) -> GroupMember:
        """Idempotent GroupMember upsert keyed on ``(group_id, course_member_id)``."""
        existing = self.db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.course_member_id == course_member_id,
        ).first()
        if existing:
            return existing
        gm = GroupMember(group_id=group_id, course_member_id=course_member_id)
        self.db.add(gm)
        self.db.flush()
        return gm

    def extend_deployment(self, deployment_id: str, runtime_months: int) -> Deployment:
        """Push ``expires_at`` out by ``runtime_months`` months.

        Anchored on ``max(now, current_expires_at)`` so that an
        already-expired-but-not-yet-deleted deployment is extended from now
        rather than from the stale past, while a still-valid deployment
        stacks the new window on top of its existing end date.

        The companion ``expiry_warning_at`` is recomputed from the new
        runtime so the UI banner timing matches.

        Args:
            deployment_id: ID of the deployment to extend.
            runtime_months: Months to add (validated by ``DeploymentExtend``).

        Returns:
            The updated deployment.

        Raises:
            NotFoundException: If no such deployment exists.
            BadRequestException: If the deployment is in a terminal state
                                 (DELETED) where extending makes no sense.
        """
        deployment = self.deployment_repo.get_by_id(deployment_id)
        if not deployment:
            raise NotFoundException(f"Deployment {deployment_id} not found")

        if deployment.status == DeploymentStatus.DELETED:
            raise BadRequestException(
                "Deployment is already deleted and cannot be extended"
            )

        now = utcnow()
        new_expires_at, new_warning_at = compute_extension(
            now=now,
            current_expires_at=deployment.expires_at,
            runtime_months=runtime_months,
        )

        deployment.expires_at = new_expires_at
        deployment.expiry_warning_at = new_warning_at
        self.db.commit()
        self.db.refresh(deployment)

        # Audit trail — the lifecycle policy is operationally significant.
        self.log_service.log(
            deployment_id=str(deployment.id),
            event_type=DeploymentLogEventType.DEPLOYMENT_LIFETIME_EXTENDED,
            message=f"Deployment lifetime extended by {runtime_months} months",
            level=DeploymentLogLevel.INFO,
            details={
                "runtime_months_added": runtime_months,
                "expires_at": new_expires_at.isoformat(),
                "expiry_warning_at": new_warning_at.isoformat(),
            },
        )

        return deployment
    
    def list_deployments(
        self,
        skip: int = 0,
        limit: int = 100,
        course_id: Optional[UUID] = None,
        status: Optional[DeploymentStatus] = None,
    ) -> tuple[list[Deployment], int]:
        """List deployments with optional filters and pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            course_id: Filter by course ID
            status: Filter by deployment status
            
        Returns:
            Tuple of (list of deployments, total count)
        """
        return self.deployment_repo.get_all_filtered(
            skip=skip,
            limit=limit,
            course_id=course_id,
            status=status,
        )
    
    def enrich_with_openstack_data(self, deployment: Deployment) -> dict:
        """Enrich deployment with live OpenStack Heat stack data.
        
        Fetches current stack status, resources, and outputs from OpenStack API.
        Falls back to database values if OpenStack data is unavailable.
        
        Args:
            deployment: Deployment instance to enrich
            
        Returns:
            Dictionary with deployment data enriched with OpenStack information
        """
        deployment_dict: dict = {
            "id": str(deployment.id),
            "template_version_id": str(deployment.template_version_id),
            "course_id": str(deployment.course_id),
            "status": deployment.status.value,
            "openstack_stack_id": deployment.openstack_stack_id,
            "deployment_parameters": deployment.deployment_parameters,
            "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
            "updated_at": deployment.updated_at.isoformat() if deployment.updated_at else None,
            "openstack_data": None
        }
        
        # Only fetch OpenStack data if stack_id exists and deployment is not deleted
        if not deployment.openstack_stack_id or deployment.status == DeploymentStatus.DELETED:
            return deployment_dict
        
        try:
            # Use the deployment's persisted OpenStack project (FK) instead of
            # re-deriving it from teacher.id and grabbing the user's first
            # OpenstackProject row — which silently picked the wrong one
            # whenever a user had more than one.
            openstack_project = deployment.openstack_project
            if not openstack_project:
                return deployment_dict

            heat_service = HeatStackService(openstack_project)
            
            # Fetch live stack data from OpenStack
            stack_info = heat_service.get_stack(deployment.openstack_stack_id)
            
            # Try to get resources (non-critical)
            try:
                resources = heat_service.get_stack_resources(deployment.openstack_stack_id)
            except Exception:
                resources = []
            
            # Try to get outputs (non-critical)
            try:
                outputs = heat_service.get_stack_outputs(deployment.openstack_stack_id)
            except Exception:
                outputs = {}
            
            deployment_dict["openstack_data"] = {
                "stack": stack_info,
                "resources": resources,
                "outputs": outputs
            }
            
        except Exception as e:
            # Log error but don't fail the entire request
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Failed to fetch OpenStack data for deployment {deployment.id}: {e}",
                exc_info=True
            )
        
        return deployment_dict
    
    def list_all_openstack_stacks(self, user_id: Optional[str] = None) -> list[dict]:
        """List all OpenStack Heat stacks with optional user filtering.
        
        Fetches stacks directly from OpenStack API and enriches them with
        deployment information from database if available.
        
        Args:
            user_id: Optional user ID to filter by. If None, returns all stacks (admin mode).
            
        Returns:
            List of stack information dicts with optional deployment metadata
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Get OpenStack projects based on user_id filter
        if user_id:
            # Lecturer mode: Get only user's projects
            openstack_projects = self.openstack_repo.get_by_owner(user_id)
            
            if not openstack_projects:
                logger.info("No OpenStack credentials found for user")
                return []
        else:
            # Admin mode: Get all projects from database
            openstack_projects = self.db.query(OpenstackProject).all()
            
            if not openstack_projects:
                logger.info("No OpenStack projects found in database")
                return []
        
        all_stacks = []
        
        # Fetch stacks from each OpenStack project
        for openstack_project in openstack_projects:
            try:
                heat_service = HeatStackService(openstack_project)
                stacks = heat_service.list_all_stacks()
                
                # Enrich with deployment data if available
                for stack in stacks:
                    stack_data = stack.copy()
                    stack_data['openstack_project_id'] = openstack_project.openstack_project_id
                    stack_data['openstack_project_name'] = openstack_project.openstack_project_name
                    stack_data['owner_user_id'] = openstack_project.owner_user_id
                    
                    # Try to find matching deployment in database
                    deployment = self.deployment_repo.db.query(Deployment).filter(
                        Deployment.openstack_stack_id == stack['stack_id']
                    ).first()
                    
                    if deployment:
                        stack_data['deployment_id'] = str(deployment.id)
                        stack_data['course_id'] = str(deployment.course_id)
                        stack_data['deployment_status'] = deployment.status.value
                    else:
                        stack_data['deployment_id'] = None
                        stack_data['course_id'] = None
                        stack_data['deployment_status'] = None
                    
                    # Try to get stack resources (non-critical)
                    try:
                        resources = heat_service.get_stack_resources(stack['stack_id'])
                        stack_data['resources'] = resources
                    except Exception:
                        stack_data['resources'] = []
                    
                    # Try to get stack outputs (non-critical)
                    try:
                        outputs = heat_service.get_stack_outputs(stack['stack_id'])
                        stack_data['outputs'] = outputs
                    except Exception:
                        stack_data['outputs'] = {}
                    
                    all_stacks.append(stack_data)
                
                logger.info(
                    f"Retrieved {len(stacks)} stacks from OpenStack project {openstack_project.openstack_project_name}"
                )
                
            except Exception as e:
                logger.error(
                    f"Failed to fetch stacks from OpenStack project {openstack_project.openstack_project_id}: {e}",
                    exc_info=True
                )
                continue
        
        return all_stacks