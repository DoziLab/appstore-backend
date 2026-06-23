"""Centralized logging configuration with JSON formatting for Loki integration."""
import logging
import sys
import json
from datetime import datetime, timezone
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging compatible with Loki.

    Outputs logs as JSON with consistent field names for easy parsing and querying.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string."""
        # Base log data
        log_data: Dict[str, Any] = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add extra fields if present (from middleware, services, etc.)
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        if hasattr(record, 'event'):
            log_data['event'] = record.event
        if hasattr(record, 'http_method'):
            log_data['http_method'] = record.http_method
        if hasattr(record, 'http_path'):
            log_data['http_path'] = record.http_path
        if hasattr(record, 'http_query'):
            log_data['http_query'] = record.http_query
        if hasattr(record, 'http_status_code'):
            log_data['http_status_code'] = record.http_status_code
        if hasattr(record, 'duration_ms'):
            log_data['duration_ms'] = record.duration_ms
        if hasattr(record, 'user_id'):
            log_data['user_id'] = record.user_id
        if hasattr(record, 'user_email'):
            log_data['user_email'] = record.user_email
        if hasattr(record, 'user_roles'):
            log_data['user_roles'] = record.user_roles
        if hasattr(record, 'client_host'):
            log_data['client_host'] = record.client_host
        if hasattr(record, 'client_port'):
            log_data['client_port'] = record.client_port
        if hasattr(record, 'user_agent'):
            log_data['user_agent'] = record.user_agent
        if hasattr(record, 'error_occurred'):
            log_data['error_occurred'] = record.error_occurred
        if hasattr(record, 'error_type'):
            log_data['error_type'] = record.error_type
        if hasattr(record, 'error_message'):
            log_data['error_message'] = record.error_message
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # Add stack trace if present
        if record.stack_info:
            log_data['stack_trace'] = record.stack_info
        
        return json.dumps(log_data, default=str)


def configure_logging(log_level: str = "INFO", json_format: bool = True) -> None:
    """
    Configure application-wide logging with JSON formatting.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Whether to use JSON formatting (recommended for production)
    """
    # Remove any existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    
    # Set formatter
    if json_format:
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    console_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.addHandler(console_handler)
    
    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    
    root_logger.info(
        "Logging configured",
        extra={
            'event': 'logging_initialized',
            'log_level': log_level,
            'json_format': json_format,
        }
    )
