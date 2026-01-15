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
    
    # OpenStack fallback credentials (optional - used when no user credentials exist)
    openstack_auth_url: str | None = None
    openstack_project_name: str | None = None
    openstack_username: str | None = None
    openstack_password: str | None = None
    openstack_user_domain_name: str | None = None
    openstack_project_domain_name: str | None = None
    openstack_region_name: str | None = None
    openstack_identity_api_version: str = "3"
    
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

