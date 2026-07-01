"""Admin cascade-delete for a lecturer account.

Ordering matters: OpenStack stacks must go down BEFORE their DB rows are
deleted, and every deployment must be torn down before its owning
template/OpenStack project — otherwise we orphan Heat stacks on
OpenStack and hit FK-constraint failures on the templates cascade.

The task calls ``delete_deployment`` synchronously (``.apply()``) rather
than via ``.delay()`` so we can observe each step's outcome and bail out
if ONE stack cleanup fails. That mirrors the single-deployment contract
we introduced earlier: a failed Heat delete keeps the DB row around so
the admin can retry, and a failed cascade keeps the whole user around
for the same reason.
"""
from __future__ import annotations

import logging
from uuid import UUID

from src.celery_app import celery_app
from src.core.database import SessionLocal
from src.models.openstack_project import OpenstackProject
from src.models.template import Template
from src.models.user import User
from src.services.lecturer_service import _deployments_for_external_id
from src.services.template_service import TemplateService
from src.tasks.deploy_tasks import delete_deployment

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="src.tasks.lecturer_tasks.cascade_delete_lecturer")
def cascade_delete_lecturer(self, user_id: str) -> dict:
    """Delete every deployment, template, and OpenStack-project row owned
    by ``user_id``, then the user row itself.

    Bail-out semantics:
      * If any ``delete_deployment`` returns ``"stack_delete_failed"`` or
        raises, the cascade stops there. The user survives so an admin
        can inspect + retry.
      * Templates and OSPs only get removed after all deployments are gone,
        because those tables carry FKs the deployments reference.

    Returns:
        dict summarising what happened, keyed by phase.
    """
    task_id = self.request.id
    db = SessionLocal()

    result = {
        "user_id": user_id,
        "task_id": task_id,
        "status": "pending",
        "deployments_deleted": 0,
        "deployments_failed": 0,
        "templates_deleted": 0,
        "openstack_projects_deleted": 0,
    }

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            result["status"] = "user_not_found"
            return result

        # ------------------------------------------------------------------
        # 1. Deployments — via delete_deployment.apply() so we can see the
        #    per-deployment outcome and abort on a Heat failure.
        # ------------------------------------------------------------------
        deployments = _deployments_for_external_id(db, user.external_id)
        logger.info(
            f"cascade_delete_lecturer: tearing down {len(deployments)} deployment(s) "
            f"for user {user_id}"
        )
        for d in deployments:
            dep_id = str(d.id)
            try:
                sub = delete_deployment.apply(args=[dep_id]).get(disable_sync_subtasks=False)
            except Exception as e:
                logger.error(
                    f"cascade_delete_lecturer: delete_deployment({dep_id}) crashed: {e}",
                    exc_info=True,
                )
                result["deployments_failed"] += 1
                result["status"] = "aborted_on_deployment_failure"
                return result

            if sub.get("status") in {"deleted", "not_found", "already_gone"}:
                result["deployments_deleted"] += 1
            else:
                # stack_delete_failed or anything else non-terminal — the
                # deployment row is intentionally kept by delete_deployment
                # so the admin can retry. Stop the cascade so we don't
                # blow away templates that the surviving deployment might
                # still need.
                logger.warning(
                    f"cascade_delete_lecturer: aborting — deployment {dep_id} "
                    f"reported status {sub.get('status')!r}"
                )
                result["deployments_failed"] += 1
                result["status"] = "aborted_on_deployment_failure"
                return result

        # ------------------------------------------------------------------
        # 2. Templates — cascade via TemplateService.delete_template (which
        #    already handles the versions -> versions_files -> approvals
        #    chain and the "still-has-deployments" check we solved for
        #    normal template deletes).
        # ------------------------------------------------------------------
        # Re-fetch after the deployment sweep so cascaded-away templates
        # don't show up.
        templates = db.query(Template).filter(Template.owner_id == user_id).all()
        template_service = TemplateService(db)
        for t in templates:
            try:
                template_service.delete_template(
                    template_id=t.id,
                    user_id=user_id,
                    is_admin=True,  # cascade runs with admin authority
                )
                result["templates_deleted"] += 1
            except Exception as e:
                logger.error(
                    f"cascade_delete_lecturer: template delete {t.id} failed: {e}",
                    exc_info=True,
                )
                result["status"] = "aborted_on_template_failure"
                return result

        # ------------------------------------------------------------------
        # 3. OpenStack projects — our DB row only. We do NOT touch Keystone
        #    (see the spec discussion): the OSP itself is a Keycloak-managed
        #    resource that other systems may reference.
        # ------------------------------------------------------------------
        osps = (
            db.query(OpenstackProject).filter(OpenstackProject.owner_user_id == user_id).all()
        )
        for op in osps:
            try:
                db.delete(op)
                db.flush()
                result["openstack_projects_deleted"] += 1
            except Exception as e:
                logger.error(
                    f"cascade_delete_lecturer: OSP delete {op.id} failed: {e}",
                    exc_info=True,
                )
                db.rollback()
                result["status"] = "aborted_on_osp_failure"
                return result

        # ------------------------------------------------------------------
        # 4. User row — safe now, nothing left FK-referencing it (for the
        #    ownership tables we handled above; historical CourseMember
        #    rows for this lecturer are cleaned up by the same GC pass
        #    delete_deployment already runs at its tail).
        # ------------------------------------------------------------------
        db.delete(user)
        db.commit()
        result["status"] = "deleted"
        logger.info(f"cascade_delete_lecturer: user {user_id} fully removed")
        return result

    except Exception as e:
        logger.exception(
            f"cascade_delete_lecturer: unexpected error for user {user_id}: {e}"
        )
        db.rollback()
        result["status"] = "failed"
        result["error"] = str(e)
        return result
    finally:
        db.close()
