"""Service to encrypt/decrypt secrets using Fernet symmetric encryption.

- Uses `cryptography.fernet.Fernet`.
- Reads key from `src.core.config.get_settings().encryption_key`.
- Exposes `encrypt(plaintext: str) -> str` and `decrypt(token: str) -> str`.
- Does not log secrets.
- Provides SQLAlchemy TypeDecorator for automatic encryption/decryption.

Rotation notes:
- The `encryption_key` should be rotated via external secret manager or env update.
- To rotate, set new key and re-encrypt stored secrets with the new key in a maintenance migration.
"""
from __future__ import annotations

from typing import Optional, Any
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator
from src.core.config import get_settings


class SecretEncryptionError(RuntimeError):
    """Raised when encryption/decryption operations fail.
    
    This includes: missing or invalid encryption key, failed encryption/decryption attempts.
    Allows specific handling of encryption-related errors vs. other runtime errors.
    """
    pass


class SecretEncryptionService:
    """Encrypt/decrypt helper using Fernet.

    The service expects a base64 urlsafe 32-byte key as returned by `Fernet.generate_key()`.
    It will raise `SecretEncryptionError` on missing key or invalid operations.
    """

    def __init__(self, key: Optional[str] = None):
        settings = get_settings()
        raw_key = key or settings.encryption_key
        if not raw_key:
            raise SecretEncryptionError("Encryption key is not configured. Set ENCRYPTION_KEY in env.")
        try:
            # If key is provided as plain text (already base64), ensure bytes
            if isinstance(raw_key, str):
                raw_key_bytes = raw_key.encode()
            else:
                raw_key_bytes = raw_key
            # Validate by constructing Fernet
            self._fernet = Fernet(raw_key_bytes)
        except Exception as e:
            raise SecretEncryptionError(f"Invalid encryption key: {e}") from e

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext and return urlsafe base64 token string.

        Do NOT log plaintext or returned token.
        """
        if plaintext is None:
            raise SecretEncryptionError("No plaintext provided for encryption")
        token = self._fernet.encrypt(plaintext.encode())
        return token.decode()

    def decrypt(self, token: str) -> str:
        """Decrypt token and return plaintext string.

        Will raise `SecretEncryptionError` for invalid token.
        """
        if not token:
            raise SecretEncryptionError("No token provided for decryption")
        try:
            plaintext = self._fernet.decrypt(token.encode())
            return plaintext.decode()
        except InvalidToken as e:
            raise SecretEncryptionError("Decryption failed: invalid token") from e
        except Exception as e:
            raise SecretEncryptionError(f"Decryption failed: {e}") from e


# Singleton instance for TypeDecorator
_encryption_service_instance: Optional[SecretEncryptionService] = None


def get_encryption_service(key: Optional[str] = None) -> SecretEncryptionService:
    """Get or create encryption service instance."""
    global _encryption_service_instance
    if _encryption_service_instance is None or key is not None:
        _encryption_service_instance = SecretEncryptionService(key=key)
    return _encryption_service_instance


class EncryptedString(TypeDecorator):
    """SQLAlchemy type that automatically encrypts/decrypts string values.

    Usage:
        password: Mapped[str] = mapped_column(EncryptedString(255))

    IMPORTANT: Never log the decrypted value.

    Behavior on misconfiguration: if ``ENCRYPTION_KEY`` is missing or invalid,
    both directions raise ``SecretEncryptionError`` — we never silently store
    or return plaintext. Treat ``ENCRYPTION_KEY`` as a hard runtime requirement.
    """
    impl = String
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[str]:
        """Encrypt value before storing in database.

        Raises ``SecretEncryptionError`` if encryption is not configured —
        better to fail the write than to persist a plaintext secret unnoticed.
        """
        if value is None:
            return None
        return get_encryption_service().encrypt(value)

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        """Decrypt value when loading from database.

        Raises ``SecretEncryptionError`` if decryption fails (missing key,
        wrong key, or corrupted token). The caller should not see a
        possibly-encrypted blob masquerading as plaintext.
        """
        if value is None:
            return None
        return get_encryption_service().decrypt(value)
