"""Ansible service — runs playbooks on a remote VM and streams output to DeploymentLog."""
import json
import logging
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Generator, Optional

from src.utils.cancellation import CancelledException
from src.utils.log_sanitizer import sanitize_message

from sqlalchemy.orm import Session

from src.models.deployment_log import DeploymentLogEventType, DeploymentLogLevel
from src.services.deployment_log_service import DeploymentLogService

logger = logging.getLogger(__name__)

# How long to wait for SSH before giving up (seconds)
SSH_TIMEOUT = 600
SSH_RETRY_INTERVAL = 10


class AnsibleService:
    """Runs Ansible playbooks on a remote VM.

    Workflow per stack:
      1. wait_for_ssh()      — polls port 22 until reachable
      2. copy_files()        — copies scripts/ and files/ to /opt/dozilab/
      3. run_playbooks()     — executes each playbook in order, streams stdout
                               line-by-line into DeploymentLog
    """

    def __init__(
        self,
        db: Session,
        deployment_id: str,
        floating_ip: str,
        ssh_private_key: str,
        ssh_user: str = "ubuntu",
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        self.db = db
        self.deployment_id = deployment_id
        self.floating_ip = floating_ip
        self.ssh_private_key = ssh_private_key
        self.ssh_user = ssh_user
        self.log_service = DeploymentLogService(db)
        # Cooperative cancellation predicate. Caller passes a closure that
        # reads the deployment's current status; the service polls it inside
        # long-running loops (SSH wait, playbook subprocess) and raises
        # CancelledException as soon as it returns True. Default: no-op.
        self._cancel_check = cancel_check or (lambda: False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wait_for_ssh(self, timeout: int = SSH_TIMEOUT) -> None:
        """Block until port 22 is reachable or timeout expires.

        Raises:
            TimeoutError: If the VM is not reachable within timeout seconds.
        """
        self._log(
            DeploymentLogEventType.SSH_WAIT,
            f"Waiting for SSH on {self.floating_ip} (timeout {timeout}s)",
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Cancel check before each poll — exits within one SSH_RETRY_INTERVAL.
            if self._cancel_check():
                raise CancelledException(
                    f"SSH wait cancelled for {self.floating_ip}"
                )
            try:
                with socket.create_connection((self.floating_ip, 22), timeout=5):
                    self._log(
                        DeploymentLogEventType.SSH_WAIT,
                        f"SSH reachable on {self.floating_ip}",
                    )
                    return
            except OSError:
                time.sleep(SSH_RETRY_INTERVAL)

        raise TimeoutError(
            f"VM {self.floating_ip} not reachable via SSH after {timeout}s"
        )

    def copy_files(
        self,
        scripts: dict[str, str],
        files: dict[str, str],
    ) -> None:
        """Copy template scripts/ and files/ to /opt/dozilab/ on the VM.

        Args:
            scripts: {filename: content} from the scripts/ folder
            files:   {filename: content} from the files/ folder
        """
        if not scripts and not files:
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Write scripts
            if scripts:
                (tmp / "scripts").mkdir()
                for name, content in scripts.items():
                    (tmp / "scripts" / name).write_text(content, encoding="utf-8")

            # Write files
            if files:
                (tmp / "files").mkdir()
                for name, content in files.items():
                    (tmp / "files" / name).write_text(content, encoding="utf-8")

            # Build a minimal playbook that copies the directories
            copy_tasks: list[dict] = [
                {
                    "name": "Secure /opt/dozilab root directory",
                    "file": {
                        "path": "/opt/dozilab",
                        "state": "directory",
                        "mode": "0700",
                        "owner": "root",
                        "group": "root",
                    },
                }
            ]
            if scripts:
                copy_tasks.append({
                    "name": "Create /opt/dozilab/scripts",
                    "file": {"path": "/opt/dozilab/scripts", "state": "directory", "mode": "0700", "owner": "root", "group": "root"},
                })
                copy_tasks.append({
                    "name": "Copy scripts",
                    "copy": {"src": str(tmp / "scripts") + "/", "dest": "/opt/dozilab/scripts/", "mode": "0700", "owner": "root", "group": "root"},
                })
            if files:
                copy_tasks.append({
                    "name": "Create /opt/dozilab/files",
                    "file": {"path": "/opt/dozilab/files", "state": "directory", "mode": "0700", "owner": "root", "group": "root"},
                })
                copy_tasks.append({
                    "name": "Copy files",
                    "copy": {"src": str(tmp / "files") + "/", "dest": "/opt/dozilab/files/", "owner": "root", "group": "root"},
                })

            import yaml as _yaml
            playbook_content = _yaml.dump([{
                "name": "DoziLab — copy template assets",
                "hosts": "all",
                "remote_user": self.ssh_user,
                "become": True,
                "tasks": copy_tasks,
            }])
            playbook_path = tmp / "copy_assets.yml"
            playbook_path.write_text(playbook_content, encoding="utf-8")

            self._log(
                DeploymentLogEventType.ANSIBLE_STARTED,
                f"Copying {len(scripts)} scripts and {len(files)} files to VM",
            )
            for line in self._run_playbook(str(playbook_path), extra_vars={}):
                pass

    def run_playbooks(
        self,
        playbooks: list[tuple[str, str]],
        extra_vars: dict,
    ) -> None:
        """Run a list of playbooks in order.

        Args:
            playbooks: List of (name, content) tuples sorted by filename.
            extra_vars: Variables passed to every playbook via --extra-vars.

        Raises:
            RuntimeError: If any playbook exits with non-zero return code.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for playbook_name, content in playbooks:
                playbook_path = tmp / playbook_name
                playbook_path.parent.mkdir(parents=True, exist_ok=True)
                playbook_path.write_text(content, encoding="utf-8")

                self._log(
                    DeploymentLogEventType.ANSIBLE_STARTED,
                    f"Running playbook: {playbook_name}",
                    details={"playbook": playbook_name},
                )

                failed = False
                for line in self._run_playbook(str(playbook_path), extra_vars):
                    if "FAILED" in line or "fatal:" in line.lower():
                        failed = True

                if failed:
                    self._log(
                        DeploymentLogEventType.ANSIBLE_FAILED,
                        f"Playbook {playbook_name} reported failures",
                        level=DeploymentLogLevel.ERROR,
                        details={"playbook": playbook_name},
                    )
                    raise RuntimeError(f"Ansible playbook {playbook_name} failed")

                self._log(
                    DeploymentLogEventType.ANSIBLE_COMPLETED,
                    f"Playbook {playbook_name} completed successfully",
                    details={"playbook": playbook_name},
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_playbook(
        self,
        playbook_path: str,
        extra_vars: dict,
    ) -> Generator[str, None, None]:
        """Execute ansible-playbook and yield each output line.

        Lines are also written to DeploymentLog in real time.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False, prefix="dozilab_ssh_"
        ) as key_file:
            key_file.write(self.ssh_private_key)
            key_path = key_file.name

        try:
            Path(key_path).chmod(0o600)

            inventory = f"{self.floating_ip},"
            cmd = [
                "ansible-playbook",
                playbook_path,
                "-i", inventory,
                "--private-key", key_path,
                "--user", self.ssh_user,
                "--ssh-extra-args", "-o StrictHostKeyChecking=no -o ConnectTimeout=10",
            ]
            if extra_vars:
                cmd += ["--extra-vars", json.dumps(extra_vars)]

            logger.debug(f"Running: {' '.join(cmd[:4])} ...")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            assert process.stdout is not None
            for raw_line in process.stdout:
                # Cancel check on every yielded line. Granularity = whatever
                # ansible-playbook prints; typically sub-second. On cancel we
                # SIGTERM the subprocess, give it 2s to clean up, then SIGKILL.
                if self._cancel_check():
                    self._log(
                        DeploymentLogEventType.ANSIBLE_FAILED,
                        "Ansible execution cancelled — terminating subprocess",
                        level=DeploymentLogLevel.WARNING,
                    )
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    raise CancelledException("Ansible execution cancelled")

                line = sanitize_message(raw_line.rstrip())
                if not line:
                    continue

                event_type, level = self._classify_line(line)
                self._log(event_type, line, level=level)
                yield line

            process.wait()
            if process.returncode != 0:
                raise RuntimeError(
                    f"ansible-playbook exited with code {process.returncode}"
                )
        finally:
            Path(key_path).unlink(missing_ok=True)

    @staticmethod
    def _classify_line(line: str) -> tuple[DeploymentLogEventType, DeploymentLogLevel]:
        """Map an ansible-playbook output line to a log event type and level."""
        upper = line.upper()
        if "TASK [" in upper:
            return DeploymentLogEventType.ANSIBLE_TASK, DeploymentLogLevel.INFO
        if upper.startswith("OK:") or " OK:" in upper:
            return DeploymentLogEventType.ANSIBLE_OK, DeploymentLogLevel.INFO
        # PLAY RECAP line: only flag as failed if failed=N where N > 0
        if "FAILED=" in upper:
            import re
            m = re.search(r"failed=(\d+)", line, re.IGNORECASE)
            if m and int(m.group(1)) > 0:
                return DeploymentLogEventType.ANSIBLE_FAILED, DeploymentLogLevel.ERROR
            return DeploymentLogEventType.ANSIBLE_TASK, DeploymentLogLevel.INFO
        if "FATAL" in upper or upper.startswith("FAILED"):
            return DeploymentLogEventType.ANSIBLE_FAILED, DeploymentLogLevel.ERROR
        if "[ERROR]" in upper:
            return DeploymentLogEventType.ANSIBLE_FAILED, DeploymentLogLevel.ERROR
        if "WARNING" in upper:
            return DeploymentLogEventType.ANSIBLE_TASK, DeploymentLogLevel.WARNING
        return DeploymentLogEventType.ANSIBLE_TASK, DeploymentLogLevel.INFO

    def _log(
        self,
        event_type: DeploymentLogEventType,
        message: str,
        level: DeploymentLogLevel = DeploymentLogLevel.INFO,
        details: dict | None = None,
    ) -> None:
        self.log_service.log(
            deployment_id=self.deployment_id,
            event_type=event_type,
            message=message,
            level=level,
            details=details,
        )
