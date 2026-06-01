"""Service for generating user_json structure per Heat stack.

This service transforms frontend deployment data into the structure that templates expect.
IMPORTANT: Each stack gets its OWN user_json with only the data for that specific stack.

Philosophy:
    - Templates expect a specific structure (course_label, instance, applications)
    - One Heat stack is created PER stack_assignment
    - Each stack gets its own user_json with only its groups/students
    - Backend creates multiple Heat stacks for one deployment

Expected Template Structures (per stack):

    **postgres-group-db:**
    ```json
    {
      "course_label": "sql-kek",
      "instance": {},
      "applications": [
        {
          "name": "postgres",
          "version": "1.3.2",
          "credentials": [
            {
              "group": 1,
              "database_name": "db_g01",
              "db_user": "grp1",
              "password": "Grp1Db-azure-tiger-42"
            }
          ],
          "admin_credentials": {
            "db_user": "teacher",
            "password": "TeacherDb-mango-cobalt-91"
          }
        }
      ]
    }
    ```

    **multistudent-ubuntu (direct VM access):**
    ```json
    {
      "course_label": "ubuntu-kurs",
      "instance": {
        "credentials": [
          { "username": "gruppe-1", "password": "Grp1-azure-tiger-42" },
          { "username": "gruppe-2", "password": "Grp2-mellow-raven-07" }
        ],
        "admin_credentials": {
          "username": "prof-berg",
          "password": "Teacher-witty-cedar-58"
        }
      },
      "applications": []
    }
    ```

Template Recognition:
    - postgres-group-db: Generates postgres + pgadmin applications
    - multistudent-ubuntu / multiuser-ubuntu: Generates instance credentials for direct VM access
    - default: Generic applications with all available data

Usage Example:
    ```python
    from src.services.template_user_management_service import TemplateUserManagementService
    
    # For each stack_assignment, generate separate user_json
    for assignment in deployment_data.stack_assignments:
        user_json = TemplateUserManagementService.generate_user_json_for_stack(
            template_name="postgres-group-db",
            course_label=deployment.name,
            stack_assignment=assignment,
            teacher=deployment_data.teacher
        )
        # Create Heat stack with this user_json
    ```
"""
from typing import Any
from src.schemas.deployment import StackAssignment, TeacherInfo
from src.utils.secure_password import generate_memorable_password


class TemplateUserManagementService:
    """Generates user_json structure for Heat templates (one per stack)."""
    
    @staticmethod
    def generate_user_json_for_stack(
        template_name: str,
        course_label: str,
        stack_assignment: StackAssignment,
        teacher: TeacherInfo,
        min_password_length: int = 12,
    ) -> dict[str, Any]:
        """Generate user_json for a SINGLE Heat stack.

        This creates the structure that templates expect. Different templates
        get different applications based on their needs.

        Args:
            template_name: Name of the template (e.g., "postgres-group-db")
            course_label: Name/label for the course (displayed in templates)
            stack_assignment: Single stack with its groups and students
            teacher: Teacher information
            min_password_length: Minimum length for generated passwords. Used to
                satisfy per-deployment pwquality policies (Heat ``pw_min_length``).

        Returns:
            Dictionary matching the structure templates expect
        """
        # Normalize template name for comparison
        template_key = template_name.lower().replace("_", "-").replace(" ", "-")

        # Route to template-specific generator
        # Currently only two template types: postgres or ubuntu
        if "postgres" in template_key:
            # PostgreSQL template: credentials in applications
            instance_data = {}
            applications = TemplateUserManagementService._generate_postgres_group_db_applications(
                stack_assignment, teacher, min_password_length
            )
        else:
            # Ubuntu/VM template: credentials in instance (default)
            instance_data = TemplateUserManagementService._generate_multistudent_ubuntu_instance(
                stack_assignment, teacher, min_password_length
            )
            applications = []

        return {
            "course_label": course_label,
            "instance": instance_data,
            "applications": applications
        }

    @staticmethod
    def _generate_postgres_group_db_applications(
        stack_assignment: StackAssignment,
        teacher: TeacherInfo,
        min_password_length: int = 12,
    ) -> list[dict[str, Any]]:
        """Generate applications for postgres-group-db template.
        
        Creates:
        - postgres application with group databases
        - pgadmin application with group access
        """
        postgres_credentials = []
        pgadmin_credentials = []
        
        for group in stack_assignment.groups:
            group_idx = group.group_index
            
            # Postgres credentials per group
            postgres_credentials.append({
                "group": group_idx,
                "database_name": f"db_g{group_idx:02d}",
                "db_user": f"grp{group_idx}",
                "password": generate_memorable_password(f"Grp{group_idx}Db", min_length=min_password_length)
            })

            # pgAdmin credentials per group
            pgadmin_credentials.append({
                "group": group_idx,
                "email": f"grp{group_idx}@dozi.local",
                "password": generate_memorable_password(f"Grp{group_idx}Pg", min_length=min_password_length)
            })

        # Teacher admin credentials
        postgres_admin = {
            "db_user": "teacher",
            "password": generate_memorable_password("TeacherDb", min_length=min_password_length)
        }

        pgadmin_admin = {
            "email": "teacher@dozi.local",
            "password": generate_memorable_password("TeacherPg", min_length=min_password_length)
        }
        
        return [
            {
                "name": "postgres",
                "version": "1.3.2",  # TODO: Make configurable or detect from template
                "credentials": postgres_credentials,
                "admin_credentials": postgres_admin
            },
            {
                "name": "pgadmin",
                "version": "4.3.2",  # TODO: Make configurable
                "credentials": pgadmin_credentials,
                "admin_credentials": pgadmin_admin
            }
        ]
    
    @staticmethod
    def _generate_multistudent_ubuntu_instance(
        stack_assignment: StackAssignment,
        teacher: TeacherInfo,
        min_password_length: int = 12,
    ) -> dict[str, Any]:
        """Generate instance data for multistudent-ubuntu template.

        This template expects credentials directly in the instance object,
        not nested in applications. Each GROUP gets one shared VM account.

        Returns:
            Dictionary with credentials (one per group) and admin_credentials
        """
        credentials = []

        # One credential per group (shared account for all students in group)
        for group in stack_assignment.groups:
            # Sanitize group name for Unix username (lowercase, alphanumeric + dash/underscore)
            unix_username = sanitize_unix_username(group.group_name)
            credentials.append({
                "username": unix_username,
                "password": generate_memorable_password(f"Grp{group.group_index}", min_length=min_password_length)
            })

        # Teacher admin account
        unix_teacher = sanitize_unix_username(teacher.username)
        admin_credentials = {
            "username": unix_teacher,
            "password": generate_memorable_password("Teacher", min_length=min_password_length)
        }

        return {
            "credentials": credentials,
            "admin_credentials": admin_credentials
        }
    
    @staticmethod
    def _generate_generic_applications(
        stack_assignment: StackAssignment,
        teacher: TeacherInfo
    ) -> list[dict[str, Any]]:
        """Generate generic applications for unknown templates.
        
        Provides raw group/student data that templates can parse themselves.
        """
        group_data = []
        
        for group in stack_assignment.groups:
            students = [
                {
                    "id": student.id,
                    "username": student.username,
                    "email": student.email,
                    "first_name": student.first_name,
                    "last_name": student.last_name,
                    "suggested_password": generate_memorable_password(
                        f"{student.first_name}{student.last_name}"
                    )
                }
                for student in group.students
            ]
            
            group_data.append({
                "group_index": group.group_index,
                "group_name": group.group_name,
                "students": students
            })
        
        return [
            {
                "name": "generic",
                "version": "1.0.0",
                "groups": group_data,
                "admin": {
                    "id": teacher.id,
                    "username": teacher.username,
                    "email": teacher.email,
                    "first_name": teacher.first_name,
                    "last_name": teacher.last_name,
                    "suggested_password": generate_memorable_password(
                        f"{teacher.first_name}{teacher.last_name}"
                    )
                }
            }
        ]


def sanitize_unix_username(name: str) -> str:
    """Sanitize a name to be a valid Unix username.
    
    Unix usernames must:
    - Start with a lowercase letter
    - Only contain lowercase letters, digits, dash (-), and underscore (_)
    - Be max 32 characters
    
    Args:
        name: Raw name (e.g., "Gruppe 1", "Prof. Berg", "Team-Alpha!")
        
    Returns:
        Valid Unix username (e.g., "gruppe-1", "prof-berg", "team-alpha")
    """
    # Convert to lowercase
    username = name.lower()
    
    # Replace spaces with dash
    username = username.replace(' ', '-')
    
    # Replace dots with dash (common in teacher names like "prof.berg")
    username = username.replace('.', '-')
    
    # Remove all chars except lowercase letters, digits, dash, underscore
    username = ''.join(c for c in username if c.isalnum() or c in '-_')
    
    # Ensure it starts with a letter (prepend 'u' if it starts with digit)
    if username and username[0].isdigit():
        username = 'u' + username
    
    # Fallback if empty after sanitization
    if not username:
        username = 'user'
    
    # Truncate to max 32 chars (Unix username limit)
    return username[:32]
