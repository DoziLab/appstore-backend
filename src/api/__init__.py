"""API module initialization"""
from fastapi import APIRouter
from src.api.deployments import router as deployments_router

# Create main API router
api_router = APIRouter(prefix="/api/v1")

api_router.include_router(deployments_router)

__all__ = [
    "api_router",
]
