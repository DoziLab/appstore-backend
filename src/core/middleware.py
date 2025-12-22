"""Custom middleware for request tracking and logging."""
import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware to track requests with unique IDs and measure processing time."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request and add tracking information."""
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Record start time
        start_time = time.time()
        
        # Log incoming request with structured fields
        logger.info(
            "Incoming request",
            extra={
                'request_id': request_id,
                'method': request.method,
                'path': request.url.path,
                'client_host': request.client.host if request.client else None,
                'event': 'request_started'
            }
        )
        
        # Process request
        response = await call_next(request)
        
        # Calculate processing time
        process_time = (time.time() - start_time) * 1000  # Convert to milliseconds
        
        # Add custom headers
        response.headers["X-Request-ID"] = request_id
        
        # Log outgoing response with structured fields
        logger.info(
            "Outgoing response",
            extra={
                'request_id': request_id,
                'method': request.method,
                'path': request.url.path,
                'status_code': response.status_code,
                'duration_ms': round(process_time, 2),
                'event': 'request_completed'
            }
        )
        
        return response
