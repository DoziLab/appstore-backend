"""Tests for the delete_deployment Celery task.

We mock at the Heat/DB boundary so the policy is exercised without a live
OpenStack or database connection. The key behaviors covered:

1. When Heat stack deletion fails, the DB row is KEPT (not silently dropped)
   and status flips to FAILED so the user can retry. Previously the row was
   wiped and the OpenStack stacks were orphaned.

2. When all Heat stack deletions succeed, the DB row IS removed end-to-end.

3. When ``openstack_stack_id`` is null, the task skips Heat and removes the
   DB row (nothing to orphan).
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.models.deployment import DeploymentStatus


# Importing the task module triggers Celery setup; do it once at module import.
from src.tasks import deploy_tasks


# Real UUID — `delete_deployment` calls UUID(deployment_id) on the DB-delete path.
_DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000001"


class _FakeTaskRequest:
    id = "task-test-1"


def _make_task():
    """Return a bound `delete_deployment` callable that mimics Celery's
    ``self`` binding without requiring a Celery worker."""
    task = deploy_tasks.delete_deployment

    class _Bound:
        request = _FakeTaskRequest()

        def __call__(self, *args, **kwargs):
            return task.run(*args, **kwargs)

    bound = _Bound()
    # Celery binds `self` via task.run() — but we use task.__wrapped__ or just
    # call via .run() with the bound task object as self.
    return bound


def _patch_session(deployment, repo_delete_returns=True):
    """Patch SessionLocal, DeploymentRepository, DeploymentLogService, and the
    DeploymentLogRepository so the task runs without touching a real DB.

    Returns the patches' MagicMock instances for assertions.
    """
    session = MagicMock()
    # db.query(...).filter(...).all() returns [] (no instances to clean up)
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.delete.return_value = 0

    repo = MagicMock()
    repo.get_by_id.return_value = deployment
    repo.delete.return_value = repo_delete_returns

    log_service = MagicMock()
    log_repo = MagicMock()
    log_repo.delete_by_deployment_id.return_value = 0

    return session, repo, log_service, log_repo


def _build_deployment(stack_id_json, openstack_project=SimpleNamespace()):
    return SimpleNamespace(
        id=_DEPLOYMENT_ID,
        status=DeploymentStatus.FAILED,
        openstack_stack_id=stack_id_json,
        openstack_project=openstack_project,
    )


def test_delete_keeps_db_row_when_heat_stack_delete_fails():
    """Bug fix: if Heat refuses to delete the stack, the DB row must stay so
    the user can retry — otherwise OpenStack is left with an orphan."""
    deployment = _build_deployment(json.dumps(["stack-abc"]))
    session, repo, log_service, log_repo = _patch_session(deployment)

    heat = MagicMock()
    heat.delete_stack.side_effect = RuntimeError("openstack 500")

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=session),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=repo),
        patch.object(deploy_tasks, "DeploymentLogService", return_value=log_service),
        patch.object(deploy_tasks, "DeploymentLogRepository", return_value=log_repo),
        patch.object(deploy_tasks, "HeatStackService", return_value=heat),
    ):
        result = deploy_tasks.delete_deployment.run(_DEPLOYMENT_ID)

    # Heat delete was attempted
    heat.delete_stack.assert_called_once_with("stack-abc")
    # DB row was NOT removed
    repo.delete.assert_not_called()
    # Status was rolled back to FAILED so the user can retry
    statuses_set = [c.args[1] for c in repo.update_status.call_args_list]
    assert DeploymentStatus.FAILED in statuses_set
    # Task reports the failure mode
    assert result["status"] == "stack_delete_failed"


def test_delete_removes_db_row_when_heat_stack_delete_succeeds():
    """Happy path: Heat reports success → the DB row is removed."""
    deployment = _build_deployment(json.dumps(["stack-abc"]))
    session, repo, log_service, log_repo = _patch_session(deployment)

    heat = MagicMock()
    heat.delete_stack.return_value = True

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=session),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=repo),
        patch.object(deploy_tasks, "DeploymentLogService", return_value=log_service),
        patch.object(deploy_tasks, "DeploymentLogRepository", return_value=log_repo),
        patch.object(deploy_tasks, "HeatStackService", return_value=heat),
    ):
        result = deploy_tasks.delete_deployment.run(_DEPLOYMENT_ID)

    heat.delete_stack.assert_called_once_with("stack-abc")
    repo.delete.assert_called_once()
    assert result["status"] == "deleted"


def test_delete_removes_db_row_when_no_openstack_stack_id():
    """When the deployment never produced a stack id (very early failure),
    there's nothing to orphan — just clean the DB row."""
    deployment = _build_deployment(stack_id_json=None)
    session, repo, log_service, log_repo = _patch_session(deployment)

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=session),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=repo),
        patch.object(deploy_tasks, "DeploymentLogService", return_value=log_service),
        patch.object(deploy_tasks, "DeploymentLogRepository", return_value=log_repo),
    ):
        result = deploy_tasks.delete_deployment.run(_DEPLOYMENT_ID)

    repo.delete.assert_called_once()
    assert result["status"] == "deleted"


def test_delete_partial_failure_keeps_surviving_stack_ids():
    """If one of N stacks fails to delete, the DB row keeps a list of the
    survivors so a retry doesn't re-target already-deleted stacks."""
    deployment = _build_deployment(json.dumps(["stack-ok", "stack-bad"]))
    session, repo, log_service, log_repo = _patch_session(deployment)

    heat = MagicMock()

    def _delete(stack_id):
        if stack_id == "stack-bad":
            raise RuntimeError("conflict")
        return True

    heat.delete_stack.side_effect = _delete

    with (
        patch.object(deploy_tasks, "SessionLocal", return_value=session),
        patch.object(deploy_tasks, "DeploymentRepository", return_value=repo),
        patch.object(deploy_tasks, "DeploymentLogService", return_value=log_service),
        patch.object(deploy_tasks, "DeploymentLogRepository", return_value=log_repo),
        patch.object(deploy_tasks, "HeatStackService", return_value=heat),
    ):
        result = deploy_tasks.delete_deployment.run(_DEPLOYMENT_ID)

    # DB row not removed
    repo.delete.assert_not_called()
    # The surviving stack id was persisted back onto the deployment
    assert deployment.openstack_stack_id == json.dumps(["stack-bad"])
    assert result["status"] == "stack_delete_failed"
