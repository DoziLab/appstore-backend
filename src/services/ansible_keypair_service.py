"""Service to ensure the DoziLab Ansible keypair exists in an OpenStack project."""
import logging
from cryptography.hazmat.primitives.serialization import (
    load_ssh_private_key,
    Encoding,
    PublicFormat,
)

import openstack

from src.models.openstack_project import OpenstackProject
from src.core.config import get_settings

logger = logging.getLogger(__name__)

KEYPAIR_NAME = "dozilab-ansible-key"


def _derive_public_key(private_key_content: str) -> str:
    """Derive the OpenSSH public key string from a private key."""
    private_key = load_ssh_private_key(
        private_key_content.encode(),
        password=None,
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.OpenSSH,
        format=PublicFormat.OpenSSH,
    )
    return pub_bytes.decode()


class AnsibleKeypairService:
    """Ensures the shared Ansible keypair exists in an OpenStack project.

    Called once when a new OpenstackProject is created or updated.
    If the keypair already exists, it is left untouched.
    If it is missing, it is created from the Backend's SSH key.
    """

    @staticmethod
    def ensure_keypair(openstack_project: OpenstackProject) -> None:
        """Register the Ansible public key in the given OpenStack project if missing.

        Args:
            openstack_project: The project to check/update.

        Raises:
            RuntimeError: If ANSIBLE_SSH_KEY_PATH is not configured.
        """
        settings = get_settings()
        private_key_content = settings.ansible_ssh_private_key

        if not private_key_content:
            raise RuntimeError(
                "ANSIBLE_SSH_KEY_PATH is not configured — cannot register Ansible keypair."
            )

        try:
            conn = openstack.connect(
                auth_url=openstack_project.auth_url,
                project_name=openstack_project.openstack_project_name,
                project_id=openstack_project.openstack_project_id,
                username=openstack_project.username,
                password=openstack_project.password,
                user_domain_name=openstack_project.user_domain_name,
                project_domain_name=openstack_project.user_domain_name,
                region_name=openstack_project.region_name,
            )

            # Check if keypair already exists
            existing = conn.compute.find_keypair(KEYPAIR_NAME)
            if existing:
                logger.info(
                    f"Ansible keypair '{KEYPAIR_NAME}' already exists in project "
                    f"{openstack_project.openstack_project_name} — skipping."
                )
                return

            # Derive public key from private key
            public_key = _derive_public_key(private_key_content)

            conn.compute.create_keypair(
                name=KEYPAIR_NAME,
                public_key=public_key,
            )
            logger.info(
                f"Ansible keypair '{KEYPAIR_NAME}' registered in project "
                f"{openstack_project.openstack_project_name}."
            )

        except Exception as e:
            logger.error(
                f"Failed to ensure Ansible keypair in project "
                f"{openstack_project.openstack_project_name}: {e}",
                exc_info=True,
            )
            raise
