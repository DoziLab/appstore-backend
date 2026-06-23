"""Tests for DeploymentCredentialService._extract_access_entries."""
from unittest.mock import MagicMock

from src.models.deployment_instance_access import AccessType
from src.services.deployment_credential_service import DeploymentCredentialService


def test_extracts_ubuntu_credentials():
    user_json = {
        "course_label": "x",
        "instance": {
            "credentials": [
                {"username": "gruppe-1", "password": "Grp1-azure-tiger-42"},
                {"username": "gruppe-2", "password": "Grp2-warm-bison-08"},
            ],
            "admin_credentials": {"username": "prof-berg", "password": "Teacher-witty-cedar-58"},
        },
        "applications": [],
    }

    rows = DeploymentCredentialService._extract_access_entries(user_json)

    assert len(rows) == 3
    assert all(r["access_type"] == AccessType.SSH for r in rows)
    assert rows[2]["username"] == "prof-berg"


def test_extracts_postgres_credentials():
    user_json = {
        "course_label": "x",
        "instance": {},
        "applications": [
            {
                "name": "postgres",
                "version": "1.3.2",
                "credentials": [
                    {"group": 1, "db_user": "grp1", "password": "Grp1Db-azure-tiger-42"},
                ],
                "admin_credentials": {"db_user": "teacher", "password": "TeacherDb-mango-cobalt-91"},
            },
            {
                "name": "pgadmin",
                "version": "4.3.2",
                "credentials": [
                    {"group": 1, "email": "grp1@x.de", "password": "Grp1Pg-warm-bison-08"},
                ],
                "admin_credentials": {"email": "teacher@x.de", "password": "TeacherPg-witty-cedar-58"},
            },
        ],
    }

    rows = DeploymentCredentialService._extract_access_entries(user_json)

    assert len(rows) == 4
    assert all(r["access_type"] == AccessType.DATABASE for r in rows)
    # Postgres credentials use db_user; pgAdmin uses email when db_user absent.
    assert rows[0]["username"] == "grp1"
    assert rows[1]["username"] == "teacher"
    assert rows[2]["username"] == "grp1@x.de"
    assert rows[3]["username"] == "teacher@x.de"


def test_skips_entries_without_password():
    user_json = {
        "instance": {
            "credentials": [{"username": "ghost", "password": None}],
        },
        "applications": [],
    }
    assert DeploymentCredentialService._extract_access_entries(user_json) == []


def test_extracts_ssh_private_keys_for_group_and_admin():
    """SSH private keys flow through both per-group credentials and admin_credentials."""
    user_json = {
        "instance": {
            "credentials": [
                {
                    "username": "gruppe-1",
                    "password": "Grp1-azure-tiger-42",
                    "ssh_private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nGROUP1KEY\n-----END OPENSSH PRIVATE KEY-----",
                },
            ],
            "admin_credentials": {
                "username": "prof-berg",
                "password": "Teacher-witty-cedar-58",
                "ssh_private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nADMINKEY\n-----END OPENSSH PRIVATE KEY-----",
            },
        },
        "applications": [],
    }

    rows = DeploymentCredentialService._extract_access_entries(user_json)

    assert len(rows) == 2
    assert "GROUP1KEY" in rows[0]["ssh_private_key"]
    assert "ADMINKEY" in rows[1]["ssh_private_key"]


def test_keeps_entries_with_only_ssh_private_key_no_password():
    """Key-only auth (no password) must still produce a row — filter is OR, not AND."""
    user_json = {
        "instance": {
            "credentials": [
                {
                    "username": "key-only",
                    "password": None,
                    "ssh_private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nKEYONLY\n-----END OPENSSH PRIVATE KEY-----",
                },
            ],
        },
        "applications": [],
    }

    rows = DeploymentCredentialService._extract_access_entries(user_json)

    assert len(rows) == 1
    assert rows[0]["username"] == "key-only"
    assert rows[0]["password"] is None
    assert "KEYONLY" in rows[0]["ssh_private_key"]


def test_extract_handles_missing_ssh_private_key_field():
    """Legacy / password-only payloads (no ssh_private_key field) still work."""
    user_json = {
        "instance": {
            "credentials": [{"username": "legacy", "password": "Pw-abc-123"}],
        },
        "applications": [],
    }
    rows = DeploymentCredentialService._extract_access_entries(user_json)
    assert len(rows) == 1
    assert rows[0]["ssh_private_key"] is None


def _instance_added_to(db_mock):
    """Return the DeploymentInstance that the service handed to db.add()."""
    from src.models.deployment_instance import DeploymentInstance
    for call in db_mock.add.call_args_list:
        obj = call.args[0]
        if isinstance(obj, DeploymentInstance):
            return obj
    raise AssertionError("DeploymentInstance was never added to the session")


def test_persists_flavor_on_instance():
    """The flavor passed in must be set on the DeploymentInstance row."""
    db = MagicMock()
    service = DeploymentCredentialService(db)

    instance = service.persist_credentials_for_stack(
        deployment_id="deploy-1",
        stack_name="my-stack",
        openstack_stack_id="stack-uuid",
        user_json={"instance": {}, "applications": []},
        flavor="gp1.medium",
    )

    assert instance.flavor == "gp1.medium"
    assert _instance_added_to(db).flavor == "gp1.medium"


def test_flavor_defaults_to_none_when_omitted():
    """Backward compat: callers that don't pass flavor still work; column stays NULL."""
    db = MagicMock()
    service = DeploymentCredentialService(db)

    instance = service.persist_credentials_for_stack(
        deployment_id="deploy-1",
        stack_name="my-stack",
        openstack_stack_id="stack-uuid",
        user_json={"instance": {}, "applications": []},
    )

    assert instance.flavor is None
