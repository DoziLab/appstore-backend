"""Models package - exports all SQLAlchemy models for proper relationship resolution."""

# Import all model classes to make them available for SQLAlchemy relationship resolution
from src.models.course import Course
from src.models.course_group import CourseGroup
from src.models.course_member import CourseMember
from src.models.deployment import Deployment, DeploymentStatus
from src.models.deployment_instance import DeploymentInstance, DeploymentInstanceStatus
from src.models.deployment_instance_access import DeploymentInstanceAccess
from src.models.deployment_log import DeploymentLog
from src.models.group_member import GroupMember
from src.models.openstack_project import OpenstackProject
from src.models.template import Template
from src.models.template_category import TemplateCategory
from src.models.template_category_assignment import TemplateCategoryAssignment
from src.models.template_version import TemplateVersion
from src.models.template_version_file import TemplateVersionFile
from src.models.user import User

__all__ = [
    "Course",
    "CourseGroup",
    "CourseMember",
    "Deployment",
    "DeploymentStatus",
    "DeploymentInstance",
    "DeploymentInstanceStatus",
    "DeploymentInstanceAccess",
    "DeploymentLog",
    "GroupMember",
    "OpenstackProject",
    "Template",
    "TemplateCategory",
    "TemplateCategoryAssignment",
    "TemplateVersion",
    "TemplateVersionFile",
    "User",
]
