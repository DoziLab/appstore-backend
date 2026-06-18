"""Schemas for the GitHub App install/disconnect/status endpoints."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class GithubInstallUrlResponse(BaseModel):
    """Response of `POST /auth/github/install`.

    Frontend redirects the browser to ``install_url``; the user picks repos /
    orgs in GitHub's UI; GitHub redirects back to ``/auth/github/install-callback``.
    """

    install_url: HttpUrl = Field(..., description="GitHub install URL with signed state")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "install_url": "https://github.com/apps/my-template-importer/installations/new?state=abc.def",
            }
        }
    )


class GithubInstalledRepo(BaseModel):
    """One repository granted to the user's GitHub App installation."""

    owner: str = Field(..., description="Repo owner login (user or org)")
    name: str = Field(..., description="Repo name")
    full_name: str = Field(..., description='"owner/name"')
    private: bool = Field(..., description="True if private repo")


class GithubInstallationStatus(BaseModel):
    """Response of `GET /auth/github/installation-status`."""

    connected: bool = Field(..., description="Whether the user has a linked install")
    installation_id: Optional[int] = Field(
        default=None, description="GitHub installation ID; null when not connected"
    )
    repos: List[GithubInstalledRepo] = Field(
        default_factory=list,
        description="Repos covered by this installation; empty when not connected",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "connected": True,
                "installation_id": 78901234,
                "repos": [
                    {
                        "owner": "octocat",
                        "name": "demo-templates",
                        "full_name": "octocat/demo-templates",
                        "private": False,
                    }
                ],
            }
        }
    )
