"""Tests for the Ed25519 SSH keypair generator."""
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    load_ssh_private_key,
    load_ssh_public_key,
)

from src.services.ssh_keypair_generator_service import generate_ed25519_keypair


def test_generate_returns_private_and_public_keys():
    """Generator returns both keys with the expected dict shape."""
    kp = generate_ed25519_keypair()
    assert set(kp.keys()) == {"private_key", "public_key"}
    assert isinstance(kp["private_key"], str)
    assert isinstance(kp["public_key"], str)


def test_private_key_is_openssh_pem():
    """Private key must be in OpenSSH PEM format (the format ssh-keygen produces)."""
    kp = generate_ed25519_keypair()
    pem = kp["private_key"]
    assert pem.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert pem.rstrip().endswith("-----END OPENSSH PRIVATE KEY-----")
    # Must be parseable as an Ed25519 private key
    parsed = load_ssh_private_key(pem.encode(), password=None)
    assert isinstance(parsed, Ed25519PrivateKey)


def test_public_key_is_single_line_openssh():
    """Public key must be in the single-line OpenSSH format used in authorized_keys."""
    kp = generate_ed25519_keypair()
    pub = kp["public_key"]
    # Single-line format: "ssh-ed25519 <base64-blob>"
    assert "\n" not in pub.strip()
    assert pub.startswith("ssh-ed25519 ")
    assert re.match(r"^ssh-ed25519 [A-Za-z0-9+/=]+", pub)
    # Must be parseable as an Ed25519 public key
    parsed = load_ssh_public_key(pub.encode())
    assert isinstance(parsed, Ed25519PublicKey)


def test_each_call_produces_a_fresh_keypair():
    """Successive calls must not return the same key — entropy check."""
    kp1 = generate_ed25519_keypair()
    kp2 = generate_ed25519_keypair()
    assert kp1["private_key"] != kp2["private_key"]
    assert kp1["public_key"] != kp2["public_key"]


def test_public_key_matches_private_key():
    """The public key in the dict must be the actual public key of the private key."""
    kp = generate_ed25519_keypair()

    priv = load_ssh_private_key(kp["private_key"].encode(), password=None)
    derived_pub = priv.public_key()
    parsed_pub = load_ssh_public_key(kp["public_key"].encode())

    # Compare raw public bytes — equality on the key objects themselves doesn't always hold.
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    assert (
        derived_pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
        == parsed_pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
