"""Custom middleware for request tracking and logging."""
import time
import uuid
import logging
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware to track requests with unique IDs, measure processing time, and log structured data."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request and add tracking information with comprehensive logging."""
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Record start time
        start_time = time.time()
        
        # Extract user information from request state if available
        user_id: Optional[str] = None
        user_email: Optional[str] = None
        user_roles: Optional[list] = None
        
        # User info is set by auth dependency after middleware, but we can try to extract from token
        try:
            if hasattr(request.state, 'user'):
                user_id = str(request.state.user.id) if hasattr(request.state.user, 'id') else None
                user_email = request.state.user.email if hasattr(request.state.user, 'email') else None
                user_roles = request.state.user.roles if hasattr(request.state.user, 'roles') else None
        except Exception:
            pass
        
        # Prepare query parameters as string
        query_params = str(dict(request.query_params)) if request.query_params else None
        
        # Log incoming request with comprehensive structured fields
        logger.info(
            "Incoming API request",
            extra={
                'request_id': request_id,
                'event': 'request_started',
                'http_method': request.method,
                'http_path': request.url.path,
                'http_query': query_params,
                'client_host': request.client.host if request.client else None,
                'client_port': request.client.port if request.client else None,
                'user_agent': request.headers.get('user-agent'),
                'user_id': user_id,
                'user_email': user_email,
                'user_roles': user_roles,
            }
        )
        
        # Process request and capture any errors
        response = None
        error_occurred = False
        error_type = None
        error_message = None
        
        try:
            response = await call_next(request)
        except Exception as e:
            error_occurred = True
            error_type = type(e).__name__
            error_message = str(e)
            logger.error(
                "Request processing failed",
                extra={
                    'request_id': request_id,
                    'event': 'request_failed',
                    'http_method': request.method,
                    'http_path': request.url.path,
                    'error_type': error_type,
                    'error_message': error_message,
                },
                exc_info=True
            )
            raise
        finally:
            # Calculate processing time
            process_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            
            if response:
                # Add custom headers
                response.headers["X-Request-ID"] = request_id
                
                # Try to get user info again after processing (might be set by auth)
                try:
                    if hasattr(request.state, 'user') and not user_id:
                        user_id = str(request.state.user.id) if hasattr(request.state.user, 'id') else None
                        user_email = request.state.user.email if hasattr(request.state.user, 'email') else None
                        user_roles = request.state.user.roles if hasattr(request.state.user, 'roles') else None
                except Exception:
                    pass
                
                # Determine log level based on status code
                status_code = response.status_code
                if status_code >= 500:
                    log_level = logging.ERROR
                elif status_code >= 400:
                    log_level = logging.WARNING
                else:
                    log_level = logging.INFO
                
                # Log outgoing response with comprehensive structured fields
                logger.log(
                    log_level,
                    "Outgoing API response",
                    extra={
                        'request_id': request_id,
                        'event': 'request_completed',
                        'http_method': request.method,
                        'http_path': request.url.path,
                        'http_status_code': status_code,
                        'duration_ms': round(process_time, 2),
                        'user_id': user_id,
                        'user_email': user_email,
                        'user_roles': user_roles,
                        'error_occurred': error_occurred,
                        'error_type': error_type,
                    }
                )
        
        return response
