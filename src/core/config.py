"""Application configuration using Pydantic Settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = "Teaching App Store Backend"
    app_version: str = "0.1.0"
    debug: bool = False
    
    # Redis / Celery (required)
    redis_url: str
    
    # Database (required)
    db_user: str
    db_password: str
    db_host: str
    db_port: int
    db_name: str
    
    # Keycloak Authentication (required)
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_jwks_cache_ttl: int = 3600  # 1 hour in seconds
    
    # Encryption key for secrets (Fernet key)
    encryption_key: str | None = None

    # Ansible SSH key — Pfad zur privaten Key-Datei (chmod 600)
    # Der zugehörige Public Key muss in OpenStack als key_name registriert sein.
    ansible_ssh_key_path: str | None = None
    ansible_ssh_key_name: str = "dozilab-ansible-key"  # Name des keypairs in OpenStack

    # Pfad zum appstore-apps Verzeichnis (für _common Playbooks)
    appstore_apps_path: str = "/app/appstore-apps"

    @property
    def ansible_ssh_private_key(self) -> str | None:
        """Read SSH private key content from file path."""
        if not self.ansible_ssh_key_path:
            return None
        try:
            from pathlib import Path
            return Path(self.ansible_ssh_key_path).read_text()
        except OSError as e:
            import logging
            logging.getLogger(__name__).error(f"Cannot read SSH key from {self.ansible_ssh_key_path}: {e}")
            return None

    # GitHub App (used by /import-from-github and /auth/github/* endpoints)
    # All optional at boot; the import endpoints raise a clear error if unset.
    github_app_id: int | None = None
    github_app_slug: str | None = None
    github_app_private_key: str | None = None
    github_app_state_secret: str | None = None
    frontend_base_url: str = "http://localhost:5173"


    @property
    def database_url(self) -> str:
        """Build database URL from components."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @property
    def keycloak_issuer(self) -> str:
        """Build Keycloak token issuer URL."""
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"
    
    @property
    def keycloak_jwks_url(self) -> str:
        """Build Keycloak JWKS (JSON Web Key Set) URL for public key retrieval."""
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"

    @property
    def keycloak_realm_url(self) -> str:
        """Build Keycloak realm URL."""
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

