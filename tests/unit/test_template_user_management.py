"""Tests for randomized credential generation in the user-management service."""
from src.schemas.deployment import GroupInfo, StackAssignment, StudentInfo, TeacherInfo
from src.services.template_user_management_service import TemplateUserManagementService


def _make_stack(group_count: int = 2) -> StackAssignment:
    return StackAssignment(
        stack_index=1,
        groups=[
            GroupInfo(
                group_name=f"gruppe-{i}",
                group_index=i,
                students=[
                    StudentInfo(
                        id=f"kc-{i}-1",
                        username=f"student{i}1",
                        email=f"s{i}1@example.de",
                        first_name=f"S{i}1",
                        last_name="Doe",
                    )
                ],
            )
            for i in range(1, group_count + 1)
        ],
    )


def _make_teacher() -> TeacherInfo:
    return TeacherInfo(
        id="kc-teacher",
        username="prof.berg",
        email="berg@example.de",
        first_name="Eva",
        last_name="Berg",
    )


def test_ubuntu_passwords_are_random_per_call():
    """Two calls with identical input must produce different group passwords."""
    stack = _make_stack()
    teacher = _make_teacher()

    first = TemplateUserManagementService.generate_user_json_for_stack(
        template_name="multistudent-ubuntu",
        course_label="course-x",
        stack_assignment=stack,
        teacher=teacher,
    )
    second = TemplateUserManagementService.generate_user_json_for_stack(
        template_name="multistudent-ubuntu",
        course_label="course-x",
        stack_assignment=stack,
        teacher=teacher,
    )

    first_pwds = [c["password"] for c in first["instance"]["credentials"]]
    second_pwds = [c["password"] for c in second["instance"]["credentials"]]
    assert first_pwds != second_pwds
    assert first["instance"]["admin_credentials"]["password"] != second["instance"]["admin_credentials"]["password"]


def test_ubuntu_password_uses_group_prefix():
    """The new prefix uses the stable group_index, not the Unix-sanitized name."""
    stack = _make_stack(group_count=1)
    teacher = _make_teacher()

    payload = TemplateUserManagementService.generate_user_json_for_stack(
        template_name="multistudent-ubuntu",
        course_label="course-x",
        stack_assignment=stack,
        teacher=teacher,
    )
    assert payload["instance"]["credentials"][0]["password"].startswith("Grp1-")
    assert payload["instance"]["admin_credentials"]["password"].startswith("Teacher-")


def test_postgres_passwords_are_random_per_call():
    stack = _make_stack()
    teacher = _make_teacher()

    first = TemplateUserManagementService.generate_user_json_for_stack(
        template_name="postgres-group-db",
        course_label="course-x",
        stack_assignment=stack,
        teacher=teacher,
    )
    second = TemplateUserManagementService.generate_user_json_for_stack(
        template_name="postgres-group-db",
        course_label="course-x",
        stack_assignment=stack,
        teacher=teacher,
    )

    first_pg = [c["password"] for c in first["applications"][0]["credentials"]]
    second_pg = [c["password"] for c in second["applications"][0]["credentials"]]
    assert first_pg != second_pg
