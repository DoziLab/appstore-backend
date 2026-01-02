"""API module initialization"""
from fastapi import APIRouter

from src.api.deployments import router as deployments_router
from src.api.admin import router as admin_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(deployments_router)
api_router.include_router(admin_router)

__all__ = ["api_router"]
