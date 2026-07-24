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
    """Schema for creating a template.

    Icons werden nicht mehr im Metadata-Body übergeben — der Client legt
    das Template zunächst ohne Icon an und lädt anschließend optional ein
    Bild via ``POST /templates/{id}/icon`` hoch.
    """
    name: str = Field(..., description="Name of the template", max_length=255)
    description: Optional[str] = Field(None, description="Template description")
    repo_url: str = Field(..., description="Git repository URL", max_length=500)
    visibility: str = Field(default="private", description="Template visibility (private/public)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Python Flask Template",
                "description": "A template for Flask web applications",
                "repo_url": "https://github.com/example/flask-template",
                "visibility": "public"
            }
        }
    )


class TemplateUpdate(BaseModel):
    """Schema for updating a template.

    Wie ``TemplateCreate`` — kein Icon-Feld mehr. Bild-Änderungen laufen
    über den dedizierten Upload-Endpoint.
    """
    name: Optional[str] = Field(None, description="Name of the template", max_length=255)
    description: Optional[str] = Field(None, description="Template description")
    repo_url: Optional[str] = Field(None, description="Git repository URL", max_length=500)
    visibility: Optional[str] = Field(None, description="Template visibility (private/public) - Only admins can change this")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Updated Template Name",
                "description": "Updated description",
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

    # Internes Feld für die ``icon_path``-Berechnung. Wird von SQLAlchemy
    # via ``from_attributes=True`` gefüllt, aus der Response aber
    # ausgeblendet — Clients bekommen nur ``icon_path``.
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
    def icon_path(self) -> Optional[str]:
        """Relativer API-Pfad zum Icon-Bild, oder ``None``.

        Wenn ein Icon-Bild via ``POST /templates/{id}/icon`` hochgeladen
        wurde → ``/api/v1/templates/{id}/icon``. Sonst ``None`` — der
        Client rendert dann einen Default-Placeholder.

        Bewusst *path*, nicht *url*: der Wert enthält keinen Origin und
        muss vom Client gegen die API-Base-URL aufgelöst werden (dieselbe
        Base-URL, gegen die auch alle anderen ``/api/v1/*``-Calls laufen).
        """
        if self.icon is not None:
            return f"/api/v1/templates/{self.id}/icon"
        return None

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
                "visibility": "public",
                "icon_path": None,
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

    Icons werden nach dem Import optional via ``POST /templates/{id}/icon``
    hochgeladen — kein Icon-Feld mehr auf dem Import-Body.
    """
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
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
