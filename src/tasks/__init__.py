"""Celery tasks package."""
from src.tasks.deploy_tasks import deploy_stack
from src.tasks.sync_tasks import sync_git_repo

__all__ = ["deploy_stack", "sync_git_repo"]
