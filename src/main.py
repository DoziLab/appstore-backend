"""FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from src.core.config import get_settings
from src.core.database import init_db
from src.core.logging_config import configure_logging
from src.core.middleware import RequestTrackingMiddleware
from src.core.exceptions import (
    http_exception_handler,
    validation_exception_handler,
    authentication_exception_handler,
    authorization_exception_handler,
    generic_exception_handler,
    AuthenticationError,
    AuthorizationError,
)
from src.api import api_router

settings = get_settings()

# Configure structured JSON logging for Loki integration
configure_logging(
    log_level="DEBUG" if settings.debug else "INFO",
    json_format=True  # Enable JSON formatting for Loki
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
   """Application lifespan events"""
    # Startup
   logger.info(
       "Starting OpenStack Application Catalog",
       extra={'event': 'application_startup', 'version': settings.app_version}
   )
   init_db()
   logger.info("Database initialized", extra={'event': 'database_initialized'})
   
   # Seed mock data in development mode (always enabled for local development)
   from src.core.seed_data import seed_mock_data
   from src.core.database import get_db
   
   db = next(get_db())
   try:
       seed_mock_data(db)
       logger.info("Mock data seeded", extra={'event': 'mock_data_seeded'})
   except Exception as e:
       logger.error(f"Failed to seed mock data: {e}", extra={'event': 'mock_data_failed', 'error': str(e)})
   finally:
       db.close()
   
   yield

   #shutdown
   logger.info(
       "Shutting down OpenStack Application Catalog",
       extra={'event': 'application_shutdown'}
   )


app = FastAPI(
    title=settings.app_name,
    description="Backend API for the App Store",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)


# Add middleware
app.add_middleware(RequestTrackingMiddleware)

# Register exception handlers
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(AuthenticationError, authentication_exception_handler)
app.add_exception_handler(AuthorizationError, authorization_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# Include routers
app.include_router(api_router)

# Initialize Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
