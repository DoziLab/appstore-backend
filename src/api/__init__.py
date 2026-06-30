"""API module initialization"""
from fastapi import APIRouter
from src.api.deployments import router as deployments_router
from src.api.templates import router as templates_router
from src.api.template_versions import router as template_versions_router
from src.api.openstack_projects import router as openstack_projects_router
from src.api.template_version_files import router as template_version_files_router
from src.api.courses import router as courses_router
from src.api.course_filters import router as course_filters_router
from src.api.quotas import router as quotas_router
from src.api.openstack_flavors import router as openstack_flavors_router
from src.api.github_app import router as github_app_router
from src.api.student import router as student_router

# Create main API router
api_router = APIRouter(prefix="/api/v1")

api_router.include_router(deployments_router)
api_router.include_router(templates_router)
api_router.include_router(template_versions_router)
api_router.include_router(openstack_projects_router)
api_router.include_router(template_version_files_router)
api_router.include_router(courses_router)
api_router.include_router(course_filters_router)
api_router.include_router(quotas_router)
api_router.include_router(openstack_flavors_router)
api_router.include_router(github_app_router)
api_router.include_router(student_router)

__all__ = [
    "api_router",
]
