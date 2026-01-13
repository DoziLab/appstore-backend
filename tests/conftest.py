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

