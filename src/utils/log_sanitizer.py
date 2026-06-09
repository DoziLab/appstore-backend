"""Sanitize log messages before storing them in the database.

Removes passwords and other sensitive fields from Ansible output and
arbitrary log strings so they never appear in the deployment log UI.
"""
import re
from typing import Any

# Keys whose values should be redacted everywhere (case-insensitive)
_SENSITIVE_KEYS = {
    "password", "passwd", "pass", "secret", "token",
    "private_key", "ssh_key", "key", "credential",
}

# Regex patterns that match common sensitive inline patterns
_PATTERNS = [
    # 'password': 'abc123' or "password": "abc123"
    re.compile(
        r"""(['"]?(?:password|passwd|secret|token|private_key)['"]?\s*[:=]\s*)['"]?[^\s'"}{,\]]+['"]?""",
        re.IGNORECASE,
    ),
    # password_hash('sha512') output — long hash strings
    re.compile(r"\\\$[0-9a-z]+\\\$.{20,}", re.IGNORECASE),
    re.compile(r"\$[0-9a-z]+\$[^'\"\s]{20,}", re.IGNORECASE),
]


def sanitize_message(message: str) -> str:
    """Replace sensitive values in a log message string."""
    if not message:
        return message
    result = message
    for pattern in _PATTERNS:
        result = pattern.sub(lambda m: m.group(1) + "***" if m.lastindex else "***", result)
    return result


def sanitize_details(details: Any) -> Any:
    """Recursively redact sensitive keys in a dict/list structure."""
    if isinstance(details, dict):
        return {
            k: "***" if _is_sensitive_key(k) else sanitize_details(v)
            for k, v in details.items()
        }
    if isinstance(details, list):
        return [sanitize_details(item) for item in details]
    if isinstance(details, str):
        return sanitize_message(details)
    return details


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(s in lower for s in _SENSITIVE_KEYS)
