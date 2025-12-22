"""FastAPI dependencies."""
from typing import Generator, Annotated
from fastapi import Request, Depends, Query
from sqlalchemy.orm import Session

from src.core.database import SessionLocal


def get_request_id(request: Request) -> str | None:
    """Get request ID from request state."""
    return getattr(request.state, "request_id", None)


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class PaginationParams:
    """Pagination parameters."""
    
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size


# Type aliases for dependency injection
RequestID = Annotated[str | None, Depends(get_request_id)]
DBSession = Annotated[Session, Depends(get_db)]
Pagination = Annotated[PaginationParams, Depends()]
