"""Tests for CredentialGeneratorService.

Covers the new ``per_group`` schema (replacing ``per_student``) and the new
``ssh_key: generate`` magic marker that produces an Ed25519 keypair, plus the
always-on admin SSH key for the teacher.
"""
from src.schemas.deployment import GroupInfo, StackAssignment, StudentInfo, TeacherInfo
from src.services.credential_generator_service import CredentialGeneratorService


def _teacher():
    return TeacherInfo(
        id="t-1",
        username="prof.berg",
        email="prof@uni.de",
        first_name="Petra",
        last_name="Berg",
    )


def _stack_with_groups(*, count: int = 1, with_course_group_id: bool = False):
    groups = [
        GroupInfo(
            group_name=f"Gruppe {i}",
            group_index=i,
            course_group_id=f"cg-{i}" if with_course_group_id else None,
            students=[
                StudentInfo(
                    id=f"s-{i}",
                    username=f"stud{i}",
                    email=f"stud{i}@uni.de",
                    first_name="Stud",
                    last_name=str(i),
                ),
            ],
        )
        for i in range(1, count + 1)
    ]
    return StackAssignment(stack_index=1, groups=groups)


def test_teacher_always_gets_admin_ssh_key_even_with_empty_spec():
    """Admin SSH key is auto-generated for the teacher — no app.yaml entry needed."""
    creds = CredentialGeneratorService.generate(
        credentials_spec={"per_group": [], "teacher": []},
        stack_assignment=_stack_with_groups(count=0),
        teacher=_teacher(),
    )

    assert "ssh_key" in creds["teacher"]["linux"]
    assert creds["teacher"]["linux"]["ssh_key"]["private_key"].startswith(
        "-----BEGIN OPENSSH PRIVATE KEY-----"
    )
    assert creds["teacher"]["linux"]["ssh_key"]["public_key"].startswith("ssh-ed25519 ")
    # Password is still auto-generated alongside the key (both auth methods).
    assert creds["teacher"]["linux"]["password"]


def test_per_group_replaces_per_student():
    """``per_group`` is the spec key (not ``per_student``); output key is ``groups``."""
    creds = CredentialGeneratorService.generate(
        credentials_spec={
            "per_group": [{"linux": {"username": "{{ username }}", "password": "generate"}}],
            "teacher": [],
        },
        stack_assignment=_stack_with_groups(count=2),
        teacher=_teacher(),
    )

    assert "deployment_groups" in creds
    assert "students" not in creds  # hard cut — old key must not leak through
    assert "groups" not in creds  # also a hard cut: collides with Ansible's
                                   # built-in inventory dict when passed as
                                   # --extra-vars; the output key is
                                   # ``deployment_groups`` instead.
    assert len(creds["deployment_groups"]) == 2
    for entry in creds["deployment_groups"]:
        assert entry["linux"]["password"]
        assert entry["linux"]["username"] == entry["username"]


def test_per_group_ssh_key_generate_produces_keypair():
    """``ssh_key: generate`` expands to a dict with private + public keys."""
    creds = CredentialGeneratorService.generate(
        credentials_spec={
            "per_group": [{
                "linux": {
                    "username": "{{ username }}",
                    "password": "generate",
                    "ssh_key": "generate",
                },
            }],
            "teacher": [],
        },
        stack_assignment=_stack_with_groups(count=2),
        teacher=_teacher(),
    )

    for entry in creds["deployment_groups"]:
        kp = entry["linux"]["ssh_key"]
        assert isinstance(kp, dict)
        assert kp["private_key"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert kp["public_key"].startswith("ssh-ed25519 ")


def test_per_group_without_ssh_key_marker_omits_keypair():
    """No ``ssh_key`` in app.yaml → no keypair generated for groups."""
    creds = CredentialGeneratorService.generate(
        credentials_spec={
            "per_group": [{"linux": {"username": "{{ username }}", "password": "generate"}}],
            "teacher": [],
        },
        stack_assignment=_stack_with_groups(count=1),
        teacher=_teacher(),
    )

    assert "ssh_key" not in creds["deployment_groups"][0]["linux"]


def test_each_group_gets_a_distinct_keypair():
    """Different groups must receive different keys — never share private material."""
    creds = CredentialGeneratorService.generate(
        credentials_spec={
            "per_group": [{
                "linux": {"username": "{{ username }}", "ssh_key": "generate"},
            }],
            "teacher": [],
        },
        stack_assignment=_stack_with_groups(count=3),
        teacher=_teacher(),
    )

    private_keys = [g["linux"]["ssh_key"]["private_key"] for g in creds["deployment_groups"]]
    assert len(set(private_keys)) == len(private_keys)


def test_teacher_spec_can_override_auto_generated_ssh_key():
    """If the teacher spec explicitly includes ``ssh_key: generate`` it merges into linux,
    re-rolling the key — the merge logic must not duplicate or break the dict."""
    creds = CredentialGeneratorService.generate(
        credentials_spec={
            "per_group": [],
            "teacher": [{"linux": {"ssh_key": "generate"}}],
        },
        stack_assignment=_stack_with_groups(count=0),
        teacher=_teacher(),
    )

    # Still a valid keypair dict regardless of override path
    kp = creds["teacher"]["linux"]["ssh_key"]
    assert kp["private_key"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert kp["public_key"].startswith("ssh-ed25519 ")


def test_course_group_id_forwarded_when_present():
    """When the wizard passes course_group_id, the generated entry carries it.

    deploy_tasks reads this field to stamp DeploymentInstanceAccess.group_id
    for each group's credentials — the missing link that enables student
    self-service filtering.
    """
    creds = CredentialGeneratorService.generate(
        credentials_spec={"per_group": [], "teacher": []},
        stack_assignment=_stack_with_groups(count=2, with_course_group_id=True),
        teacher=_teacher(),
    )
    assert creds["deployment_groups"][0]["course_group_id"] == "cg-1"
    assert creds["deployment_groups"][1]["course_group_id"] == "cg-2"


def test_course_group_id_is_none_when_omitted():
    """Legacy wizard payloads (no course_group_id) → field is None.

    Resulting access rows get group_id=NULL → invisible to students,
    lecturer-side flow keeps working.
    """
    creds = CredentialGeneratorService.generate(
        credentials_spec={"per_group": [], "teacher": []},
        stack_assignment=_stack_with_groups(count=1, with_course_group_id=False),
        teacher=_teacher(),
    )
    assert creds["deployment_groups"][0]["course_group_id"] is None
