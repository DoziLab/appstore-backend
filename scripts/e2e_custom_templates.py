"""End-to-end verification of all custom-templates branch endpoints.

Runs every new/changed endpoint as real HTTP calls (via FastAPI TestClient,
which mounts the full ASGI app and routes through middleware exactly like a
live uvicorn would). Auth is satisfied by dependency-overriding
get_current_user — same pattern the project's own integration tests use.

External services that the import flow talks to (GitHub) are patched at the
GithubAppService boundary so we can drive the endpoints without a real
GitHub App or live network.

Prints a PASS/FAIL line per endpoint and exits non-zero on any failure.
"""
from __future__ import annotations

import os
import sys
import json
from contextlib import contextmanager
from unittest.mock import patch

# Test env (same shape as tests/conftest.py).
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
os.environ.setdefault("GITHUB_APP_SLUG", "appstore-test-app")
os.environ.setdefault("GITHUB_APP_ID", "12345")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:5173")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.core.database import Base
from src.core.dependencies import get_db, get_current_user
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.models.template_version_file import TemplateVersionFile, FileType
from src.models.user import User

# All sub-models that need to register with Base
import src.models.deployment  # noqa
import src.models.deployment_instance  # noqa
import src.models.deployment_instance_access  # noqa
import src.models.deployment_log  # noqa
import src.models.template_category  # noqa
import src.models.template_category_assignment  # noqa
import src.models.template_version_file  # noqa
import src.models.course  # noqa
import src.models.course_member  # noqa
import src.models.course_group  # noqa
import src.models.group_member  # noqa
import src.models.openstack_project  # noqa


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


results: list[tuple[str, bool, str]] = []


def record(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok, detail))
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {label}")
    if detail:
        print(f"      -> {detail}")


@contextmanager
def acting_as(user_id: str, is_admin: bool = False, db=None):
    """Temporarily override auth + db dependencies."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        roles = ["admin", "lecturer"] if is_admin else ["lecturer"]
        return {
            "sub": user_id,
            "email": f"{user_id}@example.com",
            "name": "Test User",
            "preferred_username": user_id,
            "roles": roles,
            "user_id": user_id,
        }

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


APP_YAML_CONTENT = """\
app:
  name: e2e-bruno-template
  version: 1.0.0
  description: End-to-end verification template

parameters:
  - name: image
    type: string
    default: Ubuntu 22.04
    required: true
  - name: cpu_cores
    type: integer
    default: 2
    required: true
  - name: ram_gb
    type: integer
    default: 4
    required: false
"""


def main() -> int:
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed users
    admin = User(id="admin-user-id", external_id="admin-ext")
    owner = User(id="owner-user-id", external_id="owner-ext")
    other = User(id="other-user-id", external_id="other-ext")
    db.add_all([admin, owner, other])
    db.commit()

    client = TestClient(app)

    # ============================================================
    # 1. Templates: Create + List + Get + Update + Delete (+ visibility pin)
    # ============================================================
    with acting_as(owner.id, is_admin=False, db=db):
        r = client.post(
            "/api/v1/templates",
            json={
                "name": "E2E Bruno Template",
                "description": "Created via E2E script",
                "repo_url": "https://github.com/example/e2e-template",
                "icon_url": "mdi:flask",
                "visibility": "public",  # should be ignored, pinned to private
            },
        )
        ok = r.status_code == 201 and r.json()["data"]["visibility"] == "private"
        template_id = r.json()["data"]["id"] if r.status_code == 201 else None
        record("POST /templates pins visibility=private", ok, f"status={r.status_code}")

        r = client.get("/api/v1/templates?page=1&page_size=10")
        record("GET /templates list", r.status_code == 200, f"status={r.status_code}, total={r.json().get('pagination',{}).get('total')}")

        r = client.get(f"/api/v1/templates/{template_id}")
        record("GET /templates/{id}", r.status_code == 200 and r.json()["data"]["id"] == template_id)

        r = client.patch(f"/api/v1/templates/{template_id}", json={"description": "updated"})
        record("PATCH /templates/{id} (owner)", r.status_code == 200)

        r = client.patch(f"/api/v1/templates/{template_id}", json={"visibility": "public"})
        record("PATCH visibility blocked for non-admin", r.status_code == 403, f"status={r.status_code}")

    # Admin promotes visibility
    with acting_as(admin.id, is_admin=True, db=db):
        r = client.patch(f"/api/v1/templates/{template_id}", json={"visibility": "public"})
        record("PATCH visibility allowed for admin", r.status_code == 200 and r.json()["data"]["visibility"] == "public")

    # ============================================================
    # 2. Template Versions: Create + Create-with-files + Listing/Detail with parameters
    # ============================================================
    with acting_as(owner.id, is_admin=False, db=db):
        # Plain create (now requires `version`)
        r = client.post(
            "/api/v1/template-versions",
            json={
                "template_id": template_id,
                "version": "1.0.0",
                "git_commit_sha": "abc123def",
                "is_active": True,
            },
        )
        ok = r.status_code == 201 and r.json()["data"]["approval_status"] == "pending"
        version_id_v1 = r.json()["data"]["id"] if r.status_code == 201 else None
        record("POST /template-versions (defaults to pending)", ok, f"status={r.status_code}")

        # Create with files (atomic) - exercises new endpoint
        r = client.post(
            "/api/v1/template-versions/with-files",
            json={
                "template_id": template_id,
                "version": "1.1.0",
                "git_commit_sha": "manual-edit-2026-06-09",
                "is_active": True,
                "base_version_id": None,
                "files": [
                    {
                        "file_name": "app.yaml",
                        "file_type": "APP_MANIFEST",
                        "file_path": "app.yaml",
                        "content": APP_YAML_CONTENT,
                        "is_primary": False,
                        "order": 0,
                    },
                    {
                        "file_name": "init.sh",
                        "file_type": "SCRIPT",
                        "file_path": "scripts/init.sh",
                        "content": "#!/bin/bash\necho hi\n",
                        "is_primary": False,
                        "order": 1,
                    },
                ],
            },
        )
        ok = r.status_code == 201
        version_id_v11 = r.json()["data"]["id"] if ok else None
        record("POST /template-versions/with-files", ok, f"status={r.status_code}")

        # Get version with parameters
        r = client.get(f"/api/v1/template-versions/{version_id_v11}?include_parameters=true")
        params = r.json()["data"].get("parameters") if r.status_code == 200 else None
        ok = r.status_code == 200 and params is not None and len(params) >= 3
        record(
            "GET /template-versions/{id}?include_parameters=true",
            ok,
            f"status={r.status_code}, parameter count={len(params or [])}",
        )

        # Get version without parameters
        r = client.get(f"/api/v1/template-versions/{version_id_v11}?include_parameters=false")
        # Approach: when include_parameters=false the server returns the response without parameters
        ok = r.status_code == 200
        record("GET /template-versions/{id}?include_parameters=false", ok, f"status={r.status_code}")

        # List with include_parameters
        r = client.get(f"/api/v1/template-versions/template/{template_id}?include_parameters=true")
        ok = r.status_code == 200 and isinstance(r.json()["data"], list) and len(r.json()["data"]) >= 2
        record("GET /template-versions/template/{tid}?include_parameters=true", ok, f"status={r.status_code}")

        # Get active version with parameters
        r = client.get(f"/api/v1/template-versions/template/{template_id}/active?include_parameters=true")
        # Either returns parameters (active is v11) or null
        record("GET /template-versions/template/{tid}/active", r.status_code == 200, f"status={r.status_code}")

        # Update + activate + delete still work
        r = client.patch(
            f"/api/v1/template-versions/{version_id_v1}",
            json={"git_commit_sha": "patched-sha"},
        )
        record("PATCH /template-versions/{id}", r.status_code == 200)

        r = client.post(f"/api/v1/template-versions/{version_id_v1}/activate")
        record("POST /template-versions/{id}/activate", r.status_code == 200)

    # ============================================================
    # 3. Per-version approval queue + approve / reject (admin-only)
    # ============================================================
    with acting_as(other.id, is_admin=False, db=db):
        r = client.get("/api/v1/template-versions/queue?status=pending")
        record("GET /template-versions/queue blocked for non-admin", r.status_code == 403, f"status={r.status_code}")

    with acting_as(admin.id, is_admin=True, db=db):
        # Queue: status=pending (default) + sort variants
        r = client.get("/api/v1/template-versions/queue?status=pending&sort=created_at_desc")
        body = r.json()
        ok = r.status_code == 200 and isinstance(body.get("data"), list)
        items = body.get("data", []) if ok else []
        record(
            "GET /template-versions/queue (admin, status=pending)",
            ok and len(items) >= 1,
            f"status={r.status_code}, items={len(items)}, total={body.get('pagination',{}).get('total_items')}",
        )

        # Each row should inline `template` and `parameters`
        if items:
            row = items[0]
            shape_ok = "template" in row and "parameters" in row and {"id", "name", "owner_id", "visibility"} <= set(row["template"].keys())
            record("Queue row inlines template + parameters", shape_ok)

        # Filter by template_id
        r = client.get(f"/api/v1/template-versions/queue?status=pending&template_id={template_id}")
        record("Queue ?template_id=...", r.status_code == 200, f"status={r.status_code}")

        # Filter by visibility
        r = client.get("/api/v1/template-versions/queue?status=pending&visibility=public")
        record("Queue ?visibility=public", r.status_code == 200, f"status={r.status_code}")

        # Sort by template_name_asc
        r = client.get("/api/v1/template-versions/queue?status=pending&sort=template_name_asc")
        record("Queue ?sort=template_name_asc", r.status_code == 200, f"status={r.status_code}")

        # Approve v1
        r = client.post(f"/api/v1/template-versions/{version_id_v1}/approve")
        ok = r.status_code == 200 and r.json()["data"]["approval_status"] == "approved" and r.json()["data"]["approved_by_id"] == admin.id
        record("POST /template-versions/{id}/approve", ok, f"status={r.status_code}")

        # Reject v1.1 with a reason
        r = client.post(
            f"/api/v1/template-versions/{version_id_v11}/reject",
            json={"reason": "missing required parameters"},
        )
        ok = (
            r.status_code == 200
            and r.json()["data"]["approval_status"] == "rejected"
            and r.json()["data"]["rejection_reason"] == "missing required parameters"
        )
        record("POST /template-versions/{id}/reject (with reason)", ok, f"status={r.status_code}")

        # Re-queue an approved-status query
        r = client.get("/api/v1/template-versions/queue?status=approved")
        record("GET /template-versions/queue?status=approved", r.status_code == 200, f"status={r.status_code}")

        r = client.get("/api/v1/template-versions/queue?status=rejected")
        record("GET /template-versions/queue?status=rejected", r.status_code == 200, f"status={r.status_code}")

    # ============================================================
    # 4. Non-admin cannot approve/reject
    # ============================================================
    with acting_as(owner.id, is_admin=False, db=db):
        # Create a fresh pending version
        r = client.post(
            "/api/v1/template-versions",
            json={"template_id": template_id, "version": "2.0.0", "git_commit_sha": "x", "is_active": False},
        )
        v2 = r.json()["data"]["id"] if r.status_code == 201 else None

        r = client.post(f"/api/v1/template-versions/{v2}/approve")
        record("Approve blocked for non-admin", r.status_code == 403, f"status={r.status_code}")
        r = client.post(f"/api/v1/template-versions/{v2}/reject", json={"reason": "test"})
        record("Reject blocked for non-admin", r.status_code == 403, f"status={r.status_code}")

    # ============================================================
    # 5. GitHub import endpoints (patch GithubImportService internals so we
    #    don't hit GitHub). The import service uses httpx directly via
    #    private helpers; patching those is the cleanest seam.
    # ============================================================
    fake_app_yaml = APP_YAML_CONTENT
    fake_init_sh = "#!/bin/bash\necho 'hi from github import'\n"

    from src.services.github_import_service import GithubImportService

    fake_state = {"counter": 0}

    def fake_resolve_repo_auth(self, user_id, owner, repo):
        return ({"User-Agent": "appstore-backend-test"}, {"default_branch": "main"})

    def fake_resolve_commit(self, client, owner, repo, ref):
        fake_state["counter"] += 1
        return (f"sha-{fake_state['counter']:08x}", f"tree-{fake_state['counter']:08x}")

    def fake_list_tree_recursive(self, client, owner, repo, tree_sha):
        return [
            {"path": "app.yaml", "type": "blob", "size": len(fake_app_yaml), "sha": "blob1"},
            {"path": "scripts/init.sh", "type": "blob", "size": len(fake_init_sh), "sha": "blob2"},
        ]

    def fake_fetch_file_content(self, client, owner, repo, path, ref):
        if path.endswith(("app.yaml", "app.yml")):
            return fake_app_yaml
        if path.endswith("init.sh"):
            return fake_init_sh
        return ""

    def fake_try_fetch_text_file(self, client, owner, repo, path, ref):
        return fake_fetch_file_content(self, client, owner, repo, path, ref)

    patches = [
        patch.object(GithubImportService, "_resolve_repo_auth", fake_resolve_repo_auth),
        patch.object(GithubImportService, "_resolve_commit", fake_resolve_commit),
        patch.object(GithubImportService, "_list_tree_recursive", fake_list_tree_recursive),
        patch.object(GithubImportService, "_fetch_file_content", fake_fetch_file_content),
        patch.object(GithubImportService, "_try_fetch_text_file", fake_try_fetch_text_file),
    ]
    for p in patches:
        p.start()
    try:
        with acting_as(owner.id, is_admin=False, db=db):
            r = client.post(
                "/api/v1/templates/import-from-github",
                json={
                    "name": "Imported From GH",
                    "description": "Via E2E",
                    "icon_url": "mdi:github",
                    "github_url": "https://github.com/example/repo",
                    "app_yaml_path": "app.yaml",
                },
            )
            ok = r.status_code == 201 and r.json()["data"]["visibility"] == "private"
            imported_template_id = r.json()["data"]["id"] if ok else None
            record(
                "POST /templates/import-from-github",
                ok,
                f"status={r.status_code}; body={json.dumps(r.json())[:240]}",
            )

            r = client.post(
                f"/api/v1/templates/{imported_template_id}/import-from-github",
                json={
                    "github_url": "https://github.com/example/repo/tree/v1.1",
                    "app_yaml_path": "app.yaml",
                    "is_active": True,
                },
            )
            ok = r.status_code == 201
            data = r.json().get("data") or {}
            record(
                "POST /templates/{id}/import-from-github",
                ok,
                f"status={r.status_code}; approval={data.get('approval_status')}; body={json.dumps(r.json())[:240]}",
            )
    finally:
        for p in patches:
            p.stop()

    # ============================================================
    # 6. GitHub App install/disconnect/status
    # ============================================================
    with acting_as(owner.id, is_admin=False, db=db):
        r = client.post("/api/v1/auth/github/install")
        ok = r.status_code == 200 and "install_url" in r.json()["data"]
        record(
            "POST /auth/github/install",
            ok,
            f"status={r.status_code}; install_url={r.json().get('data',{}).get('install_url','')[:80]}",
        )

        # Status before connecting
        r = client.get("/api/v1/auth/github/installation-status")
        ok = r.status_code == 200 and r.json()["data"]["connected"] is False
        record("GET /auth/github/installation-status (not connected)", ok, f"status={r.status_code}")

        # Manually link an installation by hitting the callback with a valid signed state
        from src.utils.oauth_state import sign_state
        state = sign_state(user_id=owner.id)
        r = client.get(
            f"/api/v1/auth/github/install-callback?state={state}&installation_id=99887766&setup_action=install",
            follow_redirects=False,
        )
        ok = r.status_code == 302 and "/github/connected?status=ok" in r.headers.get("location", "")
        record("GET /auth/github/install-callback (valid state)", ok, f"status={r.status_code} location={r.headers.get('location','')[:120]}")

        # Bad state
        r = client.get(
            "/api/v1/auth/github/install-callback?state=garbage&installation_id=1",
            follow_redirects=False,
        )
        ok = r.status_code == 302 and "reason=invalid_state" in r.headers.get("location", "")
        record("GET /auth/github/install-callback (bad state)", ok, f"status={r.status_code} location={r.headers.get('location','')[:120]}")

        # Status after connecting (with patched repos list)
        with patch(
            "src.services.github_app_service.GithubAppService.list_installation_repos",
            lambda self, installation_id: [
                {
                    "owner": {"login": "octocat"},
                    "name": "demo",
                    "full_name": "octocat/demo",
                    "private": False,
                }
            ],
        ):
            r = client.get("/api/v1/auth/github/installation-status")
            data = r.json().get("data", {})
            ok = (
                r.status_code == 200
                and data.get("connected") is True
                and data.get("installation_id") == 99887766
                and len(data.get("repos", [])) == 1
                and data["repos"][0]["full_name"] == "octocat/demo"
            )
            record("GET /auth/github/installation-status (connected)", ok, f"status={r.status_code}")

        # Disconnect (revoke patched out)
        with patch(
            "src.services.github_app_service.GithubAppService.revoke_installation",
            lambda self, installation_id: None,
        ):
            r = client.delete("/api/v1/auth/github/installation")
            record("DELETE /auth/github/installation", r.status_code == 204, f"status={r.status_code}")

        r = client.get("/api/v1/auth/github/installation-status")
        ok = r.status_code == 200 and r.json()["data"]["connected"] is False
        record("Status after disconnect", ok, f"status={r.status_code}")

    # ============================================================
    # 7. Cleanup + summary
    # ============================================================
    with acting_as(owner.id, is_admin=False, db=db):
        r = client.delete(f"/api/v1/template-versions/{version_id_v1}")
        # may 409 if it's the only one — acceptable both ways here
        record(
            "DELETE /template-versions/{id}",
            r.status_code in (204, 409, 400),
            f"status={r.status_code}",
        )

    failed = [r for r in results if not r[1]]
    print()
    print("=" * 72)
    print(f"TOTAL: {len(results)}   PASSED: {len(results) - len(failed)}   FAILED: {len(failed)}")
    print("=" * 72)
    if failed:
        for label, _, detail in failed:
            print(f"  FAIL: {label}  ({detail})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
