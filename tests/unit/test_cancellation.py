"""Tests for cooperative cancellation of the deploy_stack Celery task.

Covers ``src/utils/cancellation.py`` plus the cancel-check integration in
``AnsibleService``. Full deploy-task cancellation is verified end-to-end
via the API test (``test_deployment_cancel.py``) — exercising the celery
task directly would mean mocking too many seams (Heat, OpenStack, Ansible
subprocess) for it to be worth the complexity here.
"""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.models.deployment import DeploymentStatus
from src.utils.cancellation import CancelledException, is_cancel_requested


class TestIsCancelRequested:
    """The DELETING flag check the deploy task uses at every checkpoint."""

    def _patch_repo(self, deployment):
        """Patch DeploymentRepository so that .get_by_id returns the given
        Deployment instance (or None)."""
        return patch(
            "src.utils.cancellation.DeploymentRepository",
            return_value=MagicMock(get_by_id=MagicMock(return_value=deployment)),
        )

    def test_true_when_status_is_deleting(self):
        db = MagicMock()
        dep = MagicMock(status=DeploymentStatus.DELETING)
        with self._patch_repo(dep):
            assert is_cancel_requested(db, "any-id") is True

    def test_true_when_status_is_deleted(self):
        db = MagicMock()
        dep = MagicMock(status=DeploymentStatus.DELETED)
        with self._patch_repo(dep):
            assert is_cancel_requested(db, "any-id") is True

    def test_true_when_deployment_missing(self):
        """If the row vanished (race with hard delete), bail out — treat as cancel."""
        db = MagicMock()
        with self._patch_repo(None):
            assert is_cancel_requested(db, "any-id") is True

    @pytest.mark.parametrize(
        "status",
        [
            DeploymentStatus.QUEUED,
            DeploymentStatus.CREATING,
            DeploymentStatus.RUNNING,
            DeploymentStatus.RESTARTING,
            DeploymentStatus.FAILED,
        ],
    )
    def test_false_for_non_terminal_statuses(self, status):
        db = MagicMock()
        dep = MagicMock(status=status)
        with self._patch_repo(dep):
            assert is_cancel_requested(db, "any-id") is False

    def test_expires_session_cache_before_query(self):
        """The deploy task lives in a long-running Celery worker; without an
        ``expire_all`` the session would hand us a stale cached Deployment
        and miss the DELETING flip done by the API worker."""
        db = MagicMock()
        dep = MagicMock(status=DeploymentStatus.CREATING)
        with self._patch_repo(dep):
            is_cancel_requested(db, "any-id")
        db.expire_all.assert_called_once()


class TestAnsibleServiceCancellation:
    """The cancel_check predicate the deploy task wires into AnsibleService."""

    def test_wait_for_ssh_raises_immediately_on_cancel(self):
        from src.services.ansible_service import AnsibleService

        svc = AnsibleService(
            db=MagicMock(),
            deployment_id="d-1",
            floating_ip="1.2.3.4",
            ssh_private_key="-----BEGIN OPENSSH PRIVATE KEY-----\nfoo\n-----END OPENSSH PRIVATE KEY-----",
            cancel_check=lambda: True,
        )
        # No socket call should happen — cancel is checked before each poll.
        with pytest.raises(CancelledException):
            svc.wait_for_ssh(timeout=5)

    def test_wait_for_ssh_default_cancel_check_is_noop(self):
        """Old call sites without ``cancel_check`` keep behaving like before
        — the default closure is a no-op that always returns False."""
        from src.services.ansible_service import AnsibleService

        svc = AnsibleService(
            db=MagicMock(),
            deployment_id="d-1",
            floating_ip="127.0.0.1",
            ssh_private_key="x",
        )
        # No CancelledException expected. We use a 1-second timeout and a
        # bogus IP so the loop will TimeoutError quickly without us needing
        # to mock the socket layer.
        with pytest.raises(TimeoutError):
            svc.wait_for_ssh(timeout=1)

    def test_run_playbook_terminates_subprocess_on_cancel(self):
        """Mid-playbook cancel must SIGTERM the ansible-playbook subprocess
        and raise CancelledException — without this the worker would keep
        streaming output even after DELETING is set."""
        from src.services.ansible_service import AnsibleService

        # Build a service whose cancel_check fires on the very first line.
        svc = AnsibleService(
            db=MagicMock(),
            deployment_id="d-1",
            floating_ip="1.2.3.4",
            ssh_private_key="x",
            cancel_check=lambda: True,
        )

        fake_process = MagicMock()
        fake_process.stdout = iter(["line1\n", "line2\n"])
        fake_process.wait.return_value = 0
        fake_process.poll.return_value = None  # still running when terminated

        with patch.object(svc, "_log"), patch("subprocess.Popen", return_value=fake_process):
            with pytest.raises(CancelledException):
                # Drive the generator — it runs until the first cancel check.
                list(svc._run_playbook("/tmp/playbook.yml", extra_vars={}))

        # Subprocess must have been terminated.
        fake_process.terminate.assert_called_once()

    def test_run_playbook_kills_unresponsive_subprocess(self):
        """If terminate() doesn't end the subprocess within 2s, fall back to
        SIGKILL — defence against a hung ansible-playbook process."""
        from src.services.ansible_service import AnsibleService

        svc = AnsibleService(
            db=MagicMock(),
            deployment_id="d-1",
            floating_ip="1.2.3.4",
            ssh_private_key="x",
            cancel_check=lambda: True,
        )

        fake_process = MagicMock()
        fake_process.stdout = iter(["line1\n"])
        # First wait() (after terminate) times out; second (after kill) returns.
        fake_process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="ansible-playbook", timeout=2),
            0,
        ]
        fake_process.poll.return_value = None

        with patch.object(svc, "_log"), patch("subprocess.Popen", return_value=fake_process):
            with pytest.raises(CancelledException):
                list(svc._run_playbook("/tmp/playbook.yml", extra_vars={}))

        fake_process.terminate.assert_called_once()
        fake_process.kill.assert_called_once()
