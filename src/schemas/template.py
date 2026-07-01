"""Template schemas for request/response validation."""
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from datetime import datetime
from typing import Any, Optional
from src.schemas.template_version import TemplateVersionResponse


GITHUB_URL_DESCRIPTION = (
    "GitHub URL. Accepts repo root (https://github.com/owner/repo), "
    "branch/tag (https://github.com/owner/repo/tree/<ref>), "
    "or direct file (https://github.com/owner/repo/blob/<ref>/<path>/app.yaml)"
)


class TemplateCreate(BaseModel):
    """Schema for creating a template."""
    name: str = Field(..., description="Name of the template", max_length=255)
    description: Optional[str] = Field(None, description="Template description")
    repo_url: str = Field(..., description="Git repository URL", max_length=500)
    icon_url: Optional[str] = Field(None, description="Icon URL or identifier (mdi:server, fa:server, 🚀, /icons/template.svg)", max_length=500)
    visibility: str = Field(default="private", description="Template visibility (private/public)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Python Flask Template",
                "description": "A template for Flask web applications",
                "repo_url": "https://github.com/example/flask-template",
                "icon_url": "mdi:flask",
                "visibility": "public"
            }
        }
    )


class TemplateUpdate(BaseModel):
    """Schema for updating a template."""
    name: Optional[str] = Field(None, description="Name of the template", max_length=255)
    description: Optional[str] = Field(None, description="Template description")
    repo_url: Optional[str] = Field(None, description="Git repository URL", max_length=500)
    icon_url: Optional[str] = Field(None, description="Icon URL or identifier (mdi:server, fa:server, 🚀, /icons/template.svg)", max_length=500)
    visibility: Optional[str] = Field(None, description="Template visibility (private/public) - Only admins can change this")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Updated Template Name",
                "description": "Updated description",
                "icon_url": "mdi:server"
            }
        }
    )


class TemplateResponse(BaseModel):
    """Schema for template response."""
    id: str = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    owner_id: str = Field(..., description="Owner user ID")
    repo_url: str = Field(..., description="Git repository URL")
    icon_url: Optional[str] = Field(None, description="Icon URL or identifier")
    visibility: str = Field(..., description="Template visibility")
    publish_requested: bool = Field(
        default=False,
        description=(
            "True wenn der Owner das Template als 'öffentlich' angelegt hat, "
            "aber noch keine Version genehmigt wurde — Template ist aktuell "
            "PRIVATE und wartet auf die Erst-Freigabe. Sobald ein Admin die "
            "erste Version approved, flippt visibility auf PUBLIC und dieses "
            "Flag wird zurückgesetzt."
        ),
    )
    versions: Optional[list[TemplateVersionResponse]] = Field(None, description="List of template versions")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    # The owning User ORM instance is held internally so we can derive the
    # display fields below without re-querying. It is excluded from the
    # serialized response — only `owner_name`, `owner_email`, and
    # `owner_username` are exposed to clients.
    owner: Any = Field(default=None, exclude=True, repr=False)

    # Internes Feld für die ``effective_icon``-Berechnung. Wird von SQLAlchemy
    # via ``from_attributes=True`` gefüllt, aus der Response aber
    # ausgeblendet — Clients bekommen nur ``effective_icon``.
    icon: Any = Field(default=None, exclude=True, repr=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owner_name(self) -> Optional[str]:
        """Cached display name of the template owner.

        Sourced from the Keycloak token's `name` claim and refreshed on every
        login (see ``UserSyncService``). May be ``None`` for legacy users who
        have not logged in since this column was introduced — clients should
        fall back to ``owner_id`` in that case.
        """
        return getattr(self.owner, "display_name", None) if self.owner else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owner_email(self) -> Optional[str]:
        """Cached email of the template owner; ``None`` for legacy users."""
        return getattr(self.owner, "email", None) if self.owner else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owner_username(self) -> Optional[str]:
        """Cached preferred_username of the owner; ``None`` for legacy users."""
        return getattr(self.owner, "username", None) if self.owner else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_uploaded_icon(self) -> bool:
        """True wenn ein Icon-Bild via ``POST /templates/{id}/icon`` hochgeladen wurde.

        Wird aus der ``TemplateIcon``-Relation abgeleitet und dient dem
        Frontend als billiges Signal, ob ``effective_icon`` auf den
        Serve-Endpoint verweist oder auf ``icon_url``.
        """
        return self.icon is not None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_icon(self) -> Optional[str]:
        """Bevorzugter Icon-Wert für das Frontend.

        Wenn ein Icon-Bild hochgeladen wurde → ``/api/v1/templates/{id}/icon``.
        Andernfalls Fallback auf ``icon_url`` (``mdi:*``, externe URL, …).
        Ist beides leer, ist der Wert ``None`` — der Client rendert dann
        einen Default-Placeholder.
        """
        if self.icon is not None:
            return f"/api/v1/templates/{self.id}/icon"
        return self.icon_url

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "tmpl-123",
                "name": "Python Flask Template",
                "description": "A template for Flask web applications",
                "owner_id": "user-456",
                "owner_name": "Prof. Dr. Bernd Berg",
                "owner_email": "berg@dhbw.de",
                "owner_username": "bberg",
                "repo_url": "https://github.com/example/flask-template",
                "icon_url": "mdi:flask",
                "visibility": "public",
                "versions": [],
                "created_at": "2024-11-27T10:00:00Z",
                "updated_at": "2024-11-27T10:00:00Z"
            }
        }
    )


class GithubImportNewTemplate(BaseModel):
    """Body for `POST /templates/import-from-github` - creates Template + first Version.

    By default the new template is created as ``private`` (owner-only,
    no approval flow). Pass ``visibility="public"`` to make it marketplace-
    visible — the first version then enters the standard approval flow
    (``pending`` unless the caller is an admin).
    """
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    icon_url: Optional[str] = Field(None, max_length=500)
    github_url: str = Field(..., description=GITHUB_URL_DESCRIPTION, max_length=1000)
    app_yaml_path: Optional[str] = Field(
        default=None,
        description="Path to app.yaml inside the repo. Defaults to 'app.yaml' (root) when only the repo URL is given.",
        max_length=500,
    )
    visibility: Optional[str] = Field(
        default="private",
        description=(
            "Template visibility. 'private' (default) = owner-only, no approval; "
            "'public' = marketplace-visible, first version enters approval flow."
        ),
    )

    @field_validator("visibility")
    @classmethod
    def _visibility_must_be_known(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return "private"
        v = v.lower()
        if v not in ("private", "public"):
            raise ValueError("visibility must be 'private' or 'public'")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "PostgreSQL Group DB",
                "description": "Provision a Postgres VM",
                "github_url": "https://github.com/dozilab/templates",
                "app_yaml_path": "postgres/app.yaml",
                "visibility": "private",
            }
        }
    )


class GithubImportNewVersion(BaseModel):
    """Body for `POST /templates/{id}/import-from-github` - new version on existing template."""
    github_url: str = Field(..., description=GITHUB_URL_DESCRIPTION, max_length=1000)
    app_yaml_path: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True, description="Mark the imported version as active")
    replace_existing: bool = Field(
        default=False,
        description=(
            "Wenn der `app.version`-String im neuen Import bereits existiert: "
            "True → bestehende Version-Row (inkl. Files) löschen und durch den "
            "neuen Import ersetzen (blockiert wenn aktive Deployments hängen). "
            "False (Default) → Backend antwortet mit VERSION_ALREADY_EXISTS, "
            "Owner soll im Repo bumpen oder explizit ersetzen wählen."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "github_url": "https://github.com/dozilab/templates/tree/v1.1",
                "app_yaml_path": "postgres/app.yaml",
                "is_active": True,
                "replace_existing": False,
            }
        }
    )

