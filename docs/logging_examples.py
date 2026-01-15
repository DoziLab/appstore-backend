"""
Example: How to Use Structured Logging in Services

This file demonstrates best practices for structured logging throughout the application.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Example 1: Service method with structured logging
class DeploymentService:
    """Example deployment service showing structured logging patterns."""
    
    def create_deployment(
        self,
        template_id: str,
        user_id: str,
        request_id: Optional[str] = None
    ) -> dict:
        """
        Create a new deployment with comprehensive logging.
        
        Args:
            template_id: ID of the template to deploy
            user_id: ID of the user creating the deployment
            request_id: Request ID for correlation (from middleware)
        """
        # Log start of operation
        logger.info(
            "Starting deployment creation",
            extra={
                'event': 'deployment_create_started',
                'request_id': request_id,
                'user_id': user_id,
                'template_id': template_id,
            }
        )
        
        try:
            # Simulate deployment logic
            deployment_id = "dep-123"
            
            # Log success with metrics
            logger.info(
                "Deployment created successfully",
                extra={
                    'event': 'deployment_create_success',
                    'request_id': request_id,
                    'user_id': user_id,
                    'template_id': template_id,
                    'deployment_id': deployment_id,
                }
            )
            
            return {'deployment_id': deployment_id}
            
        except ValueError as e:
            # Log validation errors at WARNING level
            logger.warning(
                "Deployment validation failed",
                extra={
                    'event': 'deployment_validation_failed',
                    'request_id': request_id,
                    'user_id': user_id,
                    'template_id': template_id,
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                }
            )
            raise
            
        except Exception as e:
            # Log unexpected errors at ERROR level with stack trace
            logger.error(
                "Deployment creation failed",
                extra={
                    'event': 'deployment_create_failed',
                    'request_id': request_id,
                    'user_id': user_id,
                    'template_id': template_id,
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                },
                exc_info=True  # Include full traceback
            )
            raise


# Example 2: OpenStack integration logging
class OpenStackService:
    """Example OpenStack service showing external API call logging."""
    
    def create_stack(
        self,
        stack_name: str,
        request_id: Optional[str] = None
    ) -> str:
        """Create a Heat stack with detailed logging."""
        # Log before external API call
        logger.info(
            "Calling OpenStack Heat API",
            extra={
                'event': 'openstack_api_call_started',
                'request_id': request_id,
                'openstack_service': 'heat',
                'openstack_operation': 'stack_create',
                'stack_name': stack_name,
            }
        )
        
        import time
        start_time = time.time()
        
        try:
            # Simulate OpenStack API call
            stack_id = "stack-456"
            duration_ms = (time.time() - start_time) * 1000
            
            # Log successful API call with duration
            logger.info(
                "OpenStack Heat API call successful",
                extra={
                    'event': 'openstack_api_call_success',
                    'request_id': request_id,
                    'openstack_service': 'heat',
                    'openstack_operation': 'stack_create',
                    'stack_name': stack_name,
                    'stack_id': stack_id,
                    'duration_ms': round(duration_ms, 2),
                }
            )
            
            return stack_id
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            # Log failed API call
            logger.error(
                "OpenStack Heat API call failed",
                extra={
                    'event': 'openstack_api_call_failed',
                    'request_id': request_id,
                    'openstack_service': 'heat',
                    'openstack_operation': 'stack_create',
                    'stack_name': stack_name,
                    'duration_ms': round(duration_ms, 2),
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                },
                exc_info=True
            )
            raise


# Example 3: Celery task logging
from celery import Task

class DeploymentTask(Task):
    """Example Celery task with structured logging."""
    
    def run(self, deployment_id: str, request_id: Optional[str] = None):
        """Execute deployment task."""
        logger.info(
            "Celery task started",
            extra={
                'event': 'celery_task_started',
                'request_id': request_id,
                'task_name': self.name,
                'task_id': self.request.id,
                'deployment_id': deployment_id,
            }
        )
        
        try:
            # Task logic here
            pass
            
        except Exception as e:
            logger.error(
                "Celery task failed",
                extra={
                    'event': 'celery_task_failed',
                    'request_id': request_id,
                    'task_name': self.name,
                    'task_id': self.request.id,
                    'deployment_id': deployment_id,
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                },
                exc_info=True
            )
            raise


# Example 4: Performance monitoring
def monitor_performance(operation_name: str):
    """Decorator for monitoring function performance."""
    import time
    from functools import wraps
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            logger.debug(
                f"Starting {operation_name}",
                extra={
                    'event': 'operation_started',
                    'operation_name': operation_name,
                    'function': func.__name__,
                }
            )
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                
                logger.info(
                    f"Completed {operation_name}",
                    extra={
                        'event': 'operation_completed',
                        'operation_name': operation_name,
                        'function': func.__name__,
                        'duration_ms': round(duration_ms, 2),
                        'success': True,
                    }
                )
                
                return result
                
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                
                logger.error(
                    f"Failed {operation_name}",
                    extra={
                        'event': 'operation_failed',
                        'operation_name': operation_name,
                        'function': func.__name__,
                        'duration_ms': round(duration_ms, 2),
                        'success': False,
                        'error_type': type(e).__name__,
                        'error_message': str(e),
                    },
                    exc_info=True
                )
                raise
        
        return wrapper
    return decorator


# Usage example:
@monitor_performance("database_query")
def fetch_deployments(user_id: str):
    """Fetch deployments with automatic performance logging."""
    # Database query here
    pass


# Best Practices:
# 1. Always include 'event' field to categorize log entries
# 2. Include 'request_id' for request correlation across services
# 3. Log at appropriate levels:
#    - DEBUG: Detailed diagnostic information
#    - INFO: General information about operations
#    - WARNING: Recoverable errors, validation failures
#    - ERROR: Serious errors requiring attention
# 4. Use structured fields (extra={}) instead of string formatting
# 5. Include timing information for performance monitoring
# 6. Never log sensitive data (passwords, tokens, API keys)
# 7. Use exc_info=True for exceptions to capture stack traces
# 8. Be consistent with field names across the application
