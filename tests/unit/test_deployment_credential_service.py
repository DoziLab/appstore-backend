"""Tests for DeploymentCredentialService._extract_access_entries."""
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
