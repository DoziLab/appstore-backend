"""API module initialization"""
from fastapi import APIRouter
from src.api.deployments import router as deployments_router
from src.api.templates import router as templates_router
from src.api.openstack_projects import router as openstack_projects_router

# Create main API router
api_router = APIRouter(prefix="/api/v1")

api_router.include_router(deployments_router)
api_router.include_router(templates_router)
api_router.include_router(openstack_projects_router)

__all__ = [
    "api_router",
]
