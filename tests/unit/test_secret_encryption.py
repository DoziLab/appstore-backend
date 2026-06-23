"""Tests for SecretEncryptionService and EncryptedString TypeDecorator."""
import pytest

from src.services.secret_encryption_service import (
    EncryptedString,
    SecretEncryptionError,
    get_encryption_service,
)
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, String, text
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column


def test_encrypt_decrypt_roundtrip():
    """Test basic encryption/decryption cycle."""
    key = Fernet.generate_key().decode()
    svc = get_encryption_service(key=key)
    secret = "super-secret-value"
    token = svc.encrypt(secret)
    assert token != secret
    out = svc.decrypt(token)
    assert out == secret


def test_encrypted_string_type_decorator():
    """Test EncryptedString TypeDecorator with in-memory database."""
    # Create test model
    class Base(DeclarativeBase):
        pass

    class TestModel(Base):
        __tablename__ = "test_secrets"
        id: Mapped[int] = mapped_column(primary_key=True)
        secret_value: Mapped[str] = mapped_column(EncryptedString(255))
        plain_value: Mapped[str] = mapped_column(String(255))

    # Setup encryption
    key = Fernet.generate_key().decode()
    get_encryption_service(key=key)

    # Create in-memory database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # Test write and read
    with Session(engine) as session:
        obj = TestModel(secret_value="my-secret-password", plain_value="not-secret")
        session.add(obj)
        session.commit()
        session.refresh(obj)

        # Verify we can read decrypted value
        assert obj.secret_value == "my-secret-password"
        assert obj.plain_value == "not-secret"

    # Verify encrypted value is actually encrypted in database
    with Session(engine) as session:
        result = session.execute(text("SELECT secret_value FROM test_secrets WHERE id = 1"))
        encrypted_value = result.scalar()
        # Encrypted value should be different from plaintext
        assert encrypted_value != "my-secret-password"
        # Should start with gAAAAA (Fernet token prefix)
        assert encrypted_value.startswith("gAAAAA")


def test_encrypted_string_raises_when_encryption_misconfigured(monkeypatch):
    """Writing/reading an EncryptedString without a configured key must fail loudly.

    Silently storing plaintext or returning ciphertext masquerading as
    plaintext would be a security bug — the type decorator now propagates
    ``SecretEncryptionError`` in both directions.
    """
    import src.services.secret_encryption_service as svc_mod

    # Force the singleton to be re-created without a valid key
    monkeypatch.setattr(svc_mod, "_encryption_service_instance", None)

    # Pretend ENCRYPTION_KEY is unset for the duration of this test
    from src.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "encryption_key", None)

    decorator = EncryptedString()

    with pytest.raises(SecretEncryptionError):
        decorator.process_bind_param("plaintext-secret", dialect=None)

    with pytest.raises(SecretEncryptionError):
        decorator.process_result_value("gAAAAAfake-token", dialect=None)


def test_encrypted_string_raises_on_invalid_token(monkeypatch):
    """A garbage value in the column raises rather than returning it as plaintext."""
    # Ensure a valid key is configured first
    import src.services.secret_encryption_service as svc_mod
    monkeypatch.setattr(svc_mod, "_encryption_service_instance", None)
    get_encryption_service(key=Fernet.generate_key().decode())

    decorator = EncryptedString()

    with pytest.raises(SecretEncryptionError):
        # Not a valid Fernet token — must NOT be silently returned
        decorator.process_result_value("not-a-real-token", dialect=None)
