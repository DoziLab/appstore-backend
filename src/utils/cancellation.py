"""Cooperative cancellation for the deploy_stack Celery task.

When a user fires ``DELETE /deployments/{id}`` against a deployment that is
still in the ``CREATING`` phase, the API endpoint flips ``status`` to
``DELETING`` and enqueues ``delete_deployment``. The deploy task polls this
status at well-defined checkpoints (between Heat stacks, before each
Ansible phase, inside the SSH wait loop, inside the playbook subprocess
loop). Once it sees ``DELETING`` it stops creating new resources and exits
— leaving the now-running ``delete_deployment`` task to delete every Heat
stack that was created so far (incrementally persisted to
``deployment.openstack_stack_id``).

This is *cooperative* cancellation: the task itself decides when to stop.
We deliberately do not use Celery's ``revoke(terminate=True)`` because it
would SIGTERM the worker mid-OpenStack-call and leave inconsistent state.
"""
from __future__ import annotations

from src.models.deployment import DeploymentStatus
from src.repositories.deployment_repository import DeploymentRepository


class CancelledException(Exception):
    """Raised by long-running phases when ``is_cancel_requested`` returns True.

    Bubbles up to the deploy task's main exception handler, which logs the
    cancellation and returns instead of re-raising as a Celery failure.
    """


def is_cancel_requested(db, deployment_id: str) -> bool:
    """Return True when the deploy task should bail out at its next checkpoint.

    Triggers when:
    - the deployment is now in ``DELETING`` or ``DELETED`` state (the API
      endpoint sets DELETING the moment a DELETE request arrives, before
      it enqueues the delete task)
    - the deployment row vanished from the DB (something else cleaned up)

    ``expire_all`` is called first so SQLAlchemy's identity-map cache
    doesn't hand us a stale Deployment instance. The status flip happens
    in a different process (the API request), so the running Celery
    worker's session would otherwise never see it.
    """
    db.expire_all()
    repo = DeploymentRepository(db)
    deployment = repo.get_by_id(deployment_id)
    if deployment is None:
        return True
    return deployment.status in (
        DeploymentStatus.DELETING,
        DeploymentStatus.DELETED,
    )
