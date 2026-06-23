"""Pytest configuration and fixtures.

IMPORTANT: Environment variables are set at module import time,
before pytest even starts collecting tests.
"""
import os

# Set test environment variables BEFORE any imports
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DB_USER", "test_user")
os.environ.setdefault("DB_PASSWORD", "test_password")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("KEYCLOAK_URL", "http://localhost:8080")
os.environ.setdefault("KEYCLOAK_REALM", "test_realm")
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "test_client")
os.environ.setdefault("GITHUB_APP_STATE_SECRET", "test-state-secret-do-not-use-in-prod")
# A throwaway Fernet key so tests that touch EncryptedString columns work.
# EncryptedString now fails loudly when no key is configured (security fix);
# without this, any test that persists a row with a password or ssh_private_key
# would raise SecretEncryptionError.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "DGp59ncGf4ygfOzI13qzzZEBOtbyhpXflaxsPi97iPQ=",
)

