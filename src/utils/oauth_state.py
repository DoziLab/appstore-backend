"""HMAC-signed, expiring state token for the GitHub App install flow.

The token carries the initiating user's id from /auth/github/install through to
/auth/github/install-callback without a DB roundtrip. Signed with
`settings.github_app_state_secret` so it cannot be forged.

Format: ``<urlsafe-b64(json({user_id, nonce, exp}))>.<urlsafe-b64(hmac-sha256)>``
"""
from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256

from src.core.config import get_settings
from src.core.exceptions import BadRequestException


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _secret_bytes() -> bytes:
    secret = get_settings().github_app_state_secret
    if not secret:
        raise BadRequestException(
            "GitHub App state secret is not configured. "
            "Set GITHUB_APP_STATE_SECRET in the environment."
        )
    return secret.encode("utf-8")


def sign_state(user_id: str, ttl_seconds: int = 300) -> str:
    """Produce a signed state token bound to ``user_id`` with TTL."""
    payload = {
        "user_id": user_id,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_secret_bytes(), payload_b64.encode("ascii"), sha256).digest()
    return f"{payload_b64}.{_b64encode(sig)}"


def verify_state(token: str) -> str:
    """Verify a signed state token and return the embedded ``user_id``.

    Raises ``BadRequestException`` on any signature mismatch, malformed format,
    or expiry.
    """
    if not token or token.count(".") != 1:
        raise BadRequestException("Invalid OAuth state token format.")

    payload_b64, sig_b64 = token.split(".", 1)
    expected_sig = hmac.new(_secret_bytes(), payload_b64.encode("ascii"), sha256).digest()
    try:
        provided_sig = _b64decode(sig_b64)
    except (ValueError, base64.binascii.Error) as exc:
        raise BadRequestException("Invalid OAuth state signature.") from exc

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise BadRequestException("OAuth state signature mismatch.")

    try:
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadRequestException("Invalid OAuth state payload.") from exc

    user_id = payload.get("user_id")
    exp = payload.get("exp")
    if not isinstance(user_id, str) or not isinstance(exp, int):
        raise BadRequestException("OAuth state payload is missing required fields.")
    if exp < int(time.time()):
        raise BadRequestException("OAuth state token has expired. Please retry the connect flow.")

    return user_id
