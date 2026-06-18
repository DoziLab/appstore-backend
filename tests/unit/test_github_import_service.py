"""Unit tests for GithubImportService.

Two layers:
1. parse_github_url() - pure URL parsing, no I/O.
2. End-to-end import_to_existing_template() with httpx fully mocked, to
   exercise the "download every file in the folder" behaviour and the
   ordering contract: app.yaml at order=0, then artifact files in their
   declaration order, then non-artifact files alphabetically.
"""
import base64
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.core.exceptions import BadRequestException, NotFoundException
from src.models.template import Template, TemplateVisibility
from src.models.template_version import TemplateVersion, TemplateVersionApprovalStatus
from src.models.template_version_file import FileType
from src.services.github_import_service import GithubImportService


# ---------------------------------------------------------------------------
# parse_github_url - pure function
# ---------------------------------------------------------------------------


class TestParseGithubUrl:
    def test_accepts_repo_root(self):
        result = GithubImportService.parse_github_url("https://github.com/owner/repo")
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.ref is None
        assert result.path_from_url is None

    def test_strips_trailing_dot_git(self):
        result = GithubImportService.parse_github_url("https://github.com/owner/repo.git")
        assert result.repo == "repo"

    def test_extracts_ref_from_tree_url(self):
        result = GithubImportService.parse_github_url(
            "https://github.com/owner/repo/tree/main"
        )
        assert result.ref == "main"
        assert result.path_from_url is None

    def test_extracts_ref_and_path_from_tree_url_with_subpath(self):
        result = GithubImportService.parse_github_url(
            "https://github.com/owner/repo/tree/v1.2/postgres"
        )
        assert result.ref == "v1.2"
        assert result.path_from_url == "postgres"

    def test_extracts_ref_and_path_from_blob_url(self):
        result = GithubImportService.parse_github_url(
            "https://github.com/owner/repo/blob/main/postgres/app.yaml"
        )
        assert result.ref == "main"
        assert result.path_from_url == "postgres/app.yaml"

    def test_url_decodes_ref_and_path(self):
        # Branch names with slashes get url-encoded; path segments may contain spaces.
        result = GithubImportService.parse_github_url(
            "https://github.com/owner/repo/blob/feature%2Fnew/sub%20dir/app.yaml"
        )
        assert result.ref == "feature/new"
        assert result.path_from_url == "sub dir/app.yaml"

    def test_rejects_non_github_host(self):
        with pytest.raises(BadRequestException, match="Only github.com"):
            GithubImportService.parse_github_url("https://gitlab.com/owner/repo")

    def test_rejects_empty(self):
        with pytest.raises(BadRequestException):
            GithubImportService.parse_github_url("")

    def test_rejects_missing_repo(self):
        with pytest.raises(BadRequestException, match="owner and repo"):
            GithubImportService.parse_github_url("https://github.com/owner")

    def test_rejects_unknown_path_shape(self):
        # Anything other than tree|blob after owner/repo is treated as ambiguous
        with pytest.raises(BadRequestException, match="Unsupported GitHub URL shape"):
            GithubImportService.parse_github_url("https://github.com/owner/repo/issues")


# ---------------------------------------------------------------------------
# End-to-end import - httpx Client mocked
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _http_response(status_code: int = 200, json_body: dict | list | None = None):
    """Tiny stand-in for httpx.Response that satisfies _get()."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = ""
    return resp


def _build_mock_client(commit_sha: str, tree: list[dict], files_by_path: dict[str, dict]):
    """Mock httpx.Client whose .get() routes by URL substring.

    files_by_path maps "owner/repo:path" -> a Contents-API JSON payload.
    """
    client = MagicMock()

    def fake_get(url, params=None, headers=None):
        # Default-branch lookup: GET /repos/{owner}/{repo}
        if url.endswith("/repos/owner/repo"):
            return _http_response(200, {"default_branch": "main", "private": False})
        # Commit lookup: GET /repos/{owner}/{repo}/commits/{ref}
        if "/commits/" in url:
            return _http_response(200, {
                "sha": commit_sha,
                "commit": {"tree": {"sha": "tree-sha-xyz"}},
            })
        # Tree listing: GET /repos/{owner}/{repo}/git/trees/{tree_sha}
        if "/git/trees/" in url:
            return _http_response(200, {"tree": tree, "truncated": False})
        # Contents API: GET /repos/{owner}/{repo}/contents/{path}
        if "/contents/" in url:
            # Path comes after /contents/
            path = url.split("/contents/", 1)[1]
            payload = files_by_path.get(path)
            if payload is None:
                return _http_response(404, {"message": "not found"})
            return _http_response(200, payload)
        return _http_response(404, {"message": f"unexpected url: {url}"})

    client.get.side_effect = fake_get
    # Context manager protocol used by `with httpx.Client(...) as client:`
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


@pytest.fixture
def mock_db():
    """A MagicMock that captures .add()/.flush()/.commit() etc.

    We don't need a real session here - the import service builds ORM objects
    and adds them; we inspect what was added.
    """
    return MagicMock()


@pytest.fixture
def github_import_service(mock_db):
    service = GithubImportService(mock_db)
    # By default the user has a linked GitHub App installation that covers the repo.
    service.installation_service = MagicMock()
    service.installation_service.get_installation_id.return_value = 78901234
    service.github_app = MagicMock()
    service.github_app.get_installation_token.return_value = "ghs_fake_inst_token"
    # Stub repo lookups
    service.template_repo = MagicMock()
    service.version_repo = MagicMock()
    service.version_repo.get_by_commit_sha.return_value = None  # no duplicate
    service.file_repo = MagicMock()
    return service


@pytest.fixture
def public_template():
    t = Template()
    t.id = str(uuid4())
    t.owner_id = str(uuid4())
    t.name = "demo"
    t.repo_url = "https://github.com/owner/repo"
    t.visibility = TemplateVisibility.PUBLIC
    return t


class TestImportToExistingTemplate:
    """End-to-end behaviour of import_to_existing_template()."""

    def test_falls_back_to_public_when_user_has_no_installation(
        self, github_import_service, public_template, mock_db
    ):
        """If the user has not linked the GitHub App but the repo is public,
        the import should still succeed via unauthenticated calls.
        """
        github_import_service.installation_service.get_installation_id.return_value = None

        app_yaml = "app:\n  version: 0.1.0\n"
        tree = [{"path": "app.yaml", "type": "blob", "size": len(app_yaml)}]
        files = {"app.yaml": {"encoding": "base64", "content": _b64(app_yaml)}}
        mock_client = _build_mock_client("c1", tree, files)
        github_import_service.template_repo.get_by_id.return_value = public_template

        with patch("src.services.github_import_service.httpx.Client", return_value=mock_client):
            version = github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path=None,
                is_active=True,
                user_id=public_template.owner_id,
                user_roles=["lecturer"],
            )
        # Auth must NOT have been minted
        github_import_service.github_app.get_installation_token.assert_not_called()
        assert version.git_commit_sha == "c1"

    def test_raises_when_repo_unreachable_and_no_installation(
        self, github_import_service, public_template, mock_db
    ):
        """No installation + repo lookup 404 → clear "install our App" error."""
        github_import_service.installation_service.get_installation_id.return_value = None

        # Mock client where /repos/owner/repo returns 404 for everyone.
        client = MagicMock()

        def fake_get(url, params=None, headers=None):
            return _http_response(404, {"message": "not found"})

        client.get.side_effect = fake_get
        client.__enter__.return_value = client
        client.__exit__.return_value = False

        github_import_service.template_repo.get_by_id.return_value = public_template

        with patch("src.services.github_import_service.httpx.Client", return_value=client):
            with pytest.raises(BadRequestException, match="install our GitHub App"):
                github_import_service.import_to_existing_template(
                    template_id=public_template.id,
                    github_url="https://github.com/owner/repo",
                    app_yaml_path=None,
                    is_active=True,
                    user_id=public_template.owner_id,
                    user_roles=["lecturer"],
                )

    def test_raises_when_installation_does_not_cover_repo(
        self, github_import_service, public_template, mock_db
    ):
        """User has installation but repo is private/not in installation, and
        the public fallback also 404s → message tells user to expand install access.
        """
        # installation_id is set by the fixture (78901234)
        client = MagicMock()

        def fake_get(url, params=None, headers=None):
            # Both attempts (with and without auth) 404
            return _http_response(404, {"message": "not found"})

        client.get.side_effect = fake_get
        client.__enter__.return_value = client
        client.__exit__.return_value = False

        github_import_service.template_repo.get_by_id.return_value = public_template

        with patch("src.services.github_import_service.httpx.Client", return_value=client):
            with pytest.raises(BadRequestException, match="not covered by your GitHub App"):
                github_import_service.import_to_existing_template(
                    template_id=public_template.id,
                    github_url="https://github.com/owner/repo",
                    app_yaml_path=None,
                    is_active=True,
                    user_id=public_template.owner_id,
                    user_roles=["lecturer"],
                )

    def test_raises_when_template_missing(self, github_import_service):
        github_import_service.template_repo.get_by_id.return_value = None
        with pytest.raises(NotFoundException):
            github_import_service.import_to_existing_template(
                template_id="missing",
                github_url="https://github.com/owner/repo",
                app_yaml_path=None,
                is_active=True,
                user_id="u1",
                user_roles=["lecturer"],
            )

    def test_forbidden_for_non_owner_non_admin(self, github_import_service, public_template):
        github_import_service.template_repo.get_by_id.return_value = public_template
        from src.core.exceptions import ForbiddenException
        with pytest.raises(ForbiddenException):
            github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path=None,
                is_active=True,
                user_id="someone-else",
                user_roles=["lecturer"],
            )

    def test_imports_every_file_in_folder_with_correct_ordering(
        self, github_import_service, public_template, mock_db
    ):
        """The core behaviour: app.yaml at order 0, artifact files in declaration
        order at order 1..N, then everything else alphabetically.
        """
        app_yaml = (
            "app:\n"
            "  name: demo\n"
            "  version: 1.2.3\n"
            "artifacts:\n"
            "  heat_template: heat/main.yaml\n"
            "  cloud_init: cloud-init/init.yaml\n"
        )

        # Tree contains the artifact files plus two extra "other" files that
        # are NOT mentioned in artifacts: - they should still be imported.
        tree = [
            {"path": "app.yaml", "type": "blob", "size": len(app_yaml)},
            {"path": "heat/main.yaml", "type": "blob", "size": 50},
            {"path": "cloud-init/init.yaml", "type": "blob", "size": 30},
            {"path": "README.md", "type": "blob", "size": 12},
            {"path": "helpers/script.sh", "type": "blob", "size": 20},
            {"path": "helpers", "type": "tree"},  # directory entry - must be ignored
        ]
        files = {
            "app.yaml": {"encoding": "base64", "content": _b64(app_yaml)},
            "heat/main.yaml": {"encoding": "base64", "content": _b64("heat-content")},
            "cloud-init/init.yaml": {"encoding": "base64", "content": _b64("ci-content")},
            "README.md": {"encoding": "base64", "content": _b64("# readme")},
            "helpers/script.sh": {"encoding": "base64", "content": _b64("#!/bin/sh\necho hi\n")},
        }
        mock_client = _build_mock_client("commit-sha-abc", tree, files)

        github_import_service.template_repo.get_by_id.return_value = public_template

        with patch("src.services.github_import_service.httpx.Client", return_value=mock_client):
            version = github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path=None,  # default to "app.yaml" at root
                is_active=True,
                user_id=public_template.owner_id,
                user_roles=["lecturer"],
            )

        assert version.git_commit_sha == "commit-sha-abc"
        assert version.version == "1.2.3"  # taken from app.yaml's app.version

        # Inspect every TemplateVersionFile that was added to the session
        from src.models.template_version_file import TemplateVersionFile
        added_files = [
            call.args[0]
            for call in mock_db.add.call_args_list
            if isinstance(call.args[0], TemplateVersionFile)
        ]

        # All five text files (app.yaml + 2 artifacts + 2 others) must be present.
        # The "tree" directory entry must NOT have been imported.
        by_order = sorted(added_files, key=lambda f: f.order)
        paths_by_order = [(f.order, f.file_path) for f in by_order]
        assert paths_by_order == [
            (0, "app.yaml"),                # APP_MANIFEST
            (1, "heat/main.yaml"),          # 1st artifact
            (2, "cloud-init/init.yaml"),    # 2nd artifact
            (3, "README.md"),               # other, alphabetical
            (4, "helpers/script.sh"),       # other, alphabetical
        ]

        # File-type assignments
        by_path = {f.file_path: f for f in added_files}
        assert by_path["app.yaml"].file_type == FileType.APP_MANIFEST
        assert by_path["heat/main.yaml"].file_type == FileType.HEAT_TEMPLATE
        assert by_path["cloud-init/init.yaml"].file_type == FileType.CLOUD_INIT
        assert by_path["README.md"].file_type == FileType.OTHER
        assert by_path["helpers/script.sh"].file_type == FileType.OTHER

        # is_primary should be set ONLY on the heat_template artifact
        primary = [f.file_path for f in added_files if f.is_primary]
        assert primary == ["heat/main.yaml"]

    def test_imports_from_subfolder_only(
        self, github_import_service, public_template, mock_db
    ):
        """When app_yaml_path lives in a subfolder, only that subfolder's
        files should be imported - sibling folders must be ignored.
        """
        app_yaml = "app:\n  version: 0.1.0\nartifacts:\n  heat_template: heat.yaml\n"
        tree = [
            # Files inside the subfolder we are importing
            {"path": "postgres/app.yaml", "type": "blob", "size": len(app_yaml)},
            {"path": "postgres/heat.yaml", "type": "blob", "size": 10},
            {"path": "postgres/notes.txt", "type": "blob", "size": 5},
            # Files OUTSIDE the subfolder - must NOT be fetched
            {"path": "redis/app.yaml", "type": "blob", "size": 200},
            {"path": "README.md", "type": "blob", "size": 12},
        ]
        files = {
            "postgres/app.yaml": {"encoding": "base64", "content": _b64(app_yaml)},
            "postgres/heat.yaml": {"encoding": "base64", "content": _b64("heat-x")},
            "postgres/notes.txt": {"encoding": "base64", "content": _b64("hello")},
            # Even though available, these must not be requested
            "redis/app.yaml": {"encoding": "base64", "content": _b64("nope")},
            "README.md": {"encoding": "base64", "content": _b64("nope")},
        }
        mock_client = _build_mock_client("c1", tree, files)

        github_import_service.template_repo.get_by_id.return_value = public_template

        with patch("src.services.github_import_service.httpx.Client", return_value=mock_client):
            github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path="postgres/app.yaml",
                is_active=True,
                user_id=public_template.owner_id,
                user_roles=["lecturer"],
            )

        from src.models.template_version_file import TemplateVersionFile
        added_files = [
            call.args[0] for call in mock_db.add.call_args_list
            if isinstance(call.args[0], TemplateVersionFile)
        ]
        # Relative paths are stored relative to the app.yaml folder
        paths = sorted(f.file_path for f in added_files)
        assert paths == ["app.yaml", "heat.yaml", "notes.txt"]

        # Sanity: redis/ and root README.md were never requested via Contents API
        contents_calls = [
            c.args[0] for c in mock_client.get.call_args_list
            if "/contents/" in c.args[0]
        ]
        assert not any("redis/" in u for u in contents_calls)
        assert not any(u.endswith("/contents/README.md") for u in contents_calls)

    def test_skips_oversize_blobs(
        self, github_import_service, public_template, mock_db
    ):
        """Blobs whose size exceeds MAX_FILE_SIZE_BYTES (1MB) are skipped silently."""
        from src.services.github_import_service import MAX_FILE_SIZE_BYTES
        app_yaml = "app:\n  version: 0.1.0\n"
        tree = [
            {"path": "app.yaml", "type": "blob", "size": len(app_yaml)},
            {"path": "huge.bin", "type": "blob", "size": MAX_FILE_SIZE_BYTES + 1},
        ]
        files = {
            "app.yaml": {"encoding": "base64", "content": _b64(app_yaml)},
            # huge.bin not registered -- if it WERE fetched the test would 404
        }
        mock_client = _build_mock_client("c1", tree, files)
        github_import_service.template_repo.get_by_id.return_value = public_template

        with patch("src.services.github_import_service.httpx.Client", return_value=mock_client):
            github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path=None,
                is_active=True,
                user_id=public_template.owner_id,
                user_roles=["lecturer"],
            )
        from src.models.template_version_file import TemplateVersionFile
        added = [
            c.args[0] for c in mock_db.add.call_args_list
            if isinstance(c.args[0], TemplateVersionFile)
        ]
        assert {f.file_path for f in added} == {"app.yaml"}

    def test_admin_on_public_template_auto_approves(
        self, github_import_service, public_template, mock_db
    ):
        app_yaml = "app:\n  version: 0.1.0\n"
        tree = [{"path": "app.yaml", "type": "blob", "size": len(app_yaml)}]
        files = {"app.yaml": {"encoding": "base64", "content": _b64(app_yaml)}}
        mock_client = _build_mock_client("c1", tree, files)
        github_import_service.template_repo.get_by_id.return_value = public_template
        admin_id = str(uuid4())

        with patch("src.services.github_import_service.httpx.Client", return_value=mock_client):
            version = github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path=None,
                is_active=True,
                user_id=admin_id,
                user_roles=["admin"],
            )
        assert version.approval_status == TemplateVersionApprovalStatus.APPROVED
        assert version.approved_by_id == admin_id
        assert version.approved_at is not None

    def test_lecturer_on_public_template_stays_pending(
        self, github_import_service, public_template, mock_db
    ):
        app_yaml = "app:\n  version: 0.1.0\n"
        tree = [{"path": "app.yaml", "type": "blob", "size": len(app_yaml)}]
        files = {"app.yaml": {"encoding": "base64", "content": _b64(app_yaml)}}
        mock_client = _build_mock_client("c1", tree, files)
        github_import_service.template_repo.get_by_id.return_value = public_template

        with patch("src.services.github_import_service.httpx.Client", return_value=mock_client):
            version = github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path=None,
                is_active=True,
                user_id=public_template.owner_id,
                user_roles=["lecturer"],
            )
        assert version.approval_status == TemplateVersionApprovalStatus.PENDING
        assert version.approved_by_id is None
        assert version.approved_at is None

    def test_rejects_duplicate_commit_sha(
        self, github_import_service, public_template, mock_db
    ):
        app_yaml = "app:\n  version: 0.1.0\n"
        tree = [{"path": "app.yaml", "type": "blob", "size": len(app_yaml)}]
        files = {"app.yaml": {"encoding": "base64", "content": _b64(app_yaml)}}
        mock_client = _build_mock_client("c1", tree, files)

        github_import_service.template_repo.get_by_id.return_value = public_template
        # Simulate that this template already has a version for c1
        existing = TemplateVersion()
        existing.id = str(uuid4())
        github_import_service.version_repo.get_by_commit_sha.return_value = existing

        with patch("src.services.github_import_service.httpx.Client", return_value=mock_client):
            with pytest.raises(BadRequestException, match="already has a version"):
                github_import_service.import_to_existing_template(
                    template_id=public_template.id,
                    github_url="https://github.com/owner/repo",
                    app_yaml_path=None,
                    is_active=True,
                    user_id=public_template.owner_id,
                    user_roles=["lecturer"],
                )

    def test_rejects_non_yaml_app_path(
        self, github_import_service, public_template, mock_db
    ):
        github_import_service.template_repo.get_by_id.return_value = public_template
        with pytest.raises(BadRequestException, match=".yaml or .yml"):
            github_import_service.import_to_existing_template(
                template_id=public_template.id,
                github_url="https://github.com/owner/repo",
                app_yaml_path="postgres",
                is_active=True,
                user_id=public_template.owner_id,
                user_roles=["lecturer"],
            )
