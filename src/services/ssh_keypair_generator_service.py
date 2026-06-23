"""Generate Ed25519 SSH keypairs for deployment credentials.

Used by the credential generator to produce per-group and per-teacher SSH keys
that get injected into the VM's ``authorized_keys`` via Ansible. Private keys
are returned in OpenSSH PEM format so users can save them as standard
``~/.ssh/id_ed25519`` files; public keys are returned in the single-line
OpenSSH format expected by ``authorized_keys`` (and by Ansible's
``ansible.posix.authorized_key`` module).

Ed25519 is the default: shorter than RSA (one-line public key, ~400 byte
private key), well-supported on every modern SSH client/server, and
considered the current best practice.
"""
from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_ed25519_keypair() -> dict[str, str]:
    """Generate a fresh Ed25519 keypair.

    Returns:
        ``{"private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\\n...",
          "public_key":  "ssh-ed25519 AAAA..."}``

        ``private_key`` is in OpenSSH PEM format (unencrypted) — ready to be
        saved as ``~/.ssh/id_ed25519``.
        ``public_key`` is in single-line OpenSSH format — ready to be appended
        to ``~/.ssh/authorized_keys``.
    """
    private_key = Ed25519PrivateKey.generate()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_openssh = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("utf-8")

    return {
        "private_key": private_pem,
        "public_key": public_openssh,
    }
