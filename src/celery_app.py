"""Celery application configuration."""
import logging
from celery import Celery
from celery.signals import setup_logging

from src.core.config import get_settings
from src.core.logging_config import configure_logging

settings = get_settings()

celery_app = Celery(
    "appstore",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.tasks.deploy_tasks", "src.tasks.sync_tasks"],
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    worker_prefetch_multiplier=1,
)


@setup_logging.connect
def configure_celery_logging(**kwargs):
    """Configure Celery to use our structured JSON logging."""
    configure_logging(
        log_level="DEBUG" if settings.debug else "INFO",
        json_format=True
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "Celery worker logging configured",
        extra={'event': 'celery_logging_initialized'}
    )

