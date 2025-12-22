# App Store Backend - Copilot Instructions

## Architecture Overview

FastAPI backend using a **Service-Repository-Model** layered architecture for managing OpenStack deployments:

```
API Route → Service → Repository → Model/DB
               ↓
        Celery Task (async)
```

- **API Layer** ([src/api/](src/api/)): FastAPI routes with dependency injection. Use `ResponseBuilder` for all responses.
- **Service Layer** ([src/services/](src/services/)): Business logic orchestration. Services receive `db: Session` and instantiate repositories.
- **Repository Layer** ([src/repositories/](src/repositories/)): Database access via generic `BaseRepository[Model]` pattern.
- **Tasks** ([src/tasks/](src/tasks/)): Celery tasks for async operations (deployments, syncing).

## Key Patterns

### Dependency Injection
Use typed aliases from [src/core/dependencies.py](src/core/dependencies.py):
```python
from src.core.dependencies import DBSession, RequestID, Pagination

@router.get("")
async def list_items(db: DBSession, request_id: RequestID, pagination: Pagination):
```

### Response Format
**Always** use `ResponseBuilder` from [src/core/response_builder.py](src/core/response_builder.py):
```python
return ResponseBuilder.success(data=result, message="...", request_id=request_id)
return ResponseBuilder.created(data=result, request_id=request_id)
return ResponseBuilder.paginated(data=items, page=p.page, page_size=p.page_size, total=count, request_id=request_id)
```

### Repository Pattern
Extend `BaseRepository[Model]` for new entities. It provides: `create()`, `get_by_id()`, `get_all()`, `update()`, `delete()`.
```python
class MyRepository(BaseRepository[MyModel]):
    def __init__(self, db: Session):
        super().__init__(MyModel, db)
```

### Pydantic Schemas
- Use `model_config = {"from_attributes": True}` for ORM compatibility
- Place in [src/schemas/](src/schemas/) with `*Create`, `*Response`, `*Update` naming

### Celery Tasks
Trigger async work via `.delay()`:
```python
from src.tasks.deploy_tasks import deploy_stack
deploy_stack.delay(str(deployment.id))
```

## Developer Workflow

### Start Services
```bash
docker compose up -d          # API, PostgreSQL, Redis, Celery Worker
curl http://localhost:8000/health
```

### Local Development
```bash
pip install -e ".[dev]"
uvicorn src.main:app --reload
```

### Testing
```bash
pytest                        # Run all tests
pytest tests/api/             # API tests only
```

## Configuration
Environment via `.env` (see [src/core/config.py](src/core/config.py)):
- `DB_*`: PostgreSQL connection
- `REDIS_URL`: Celery broker/backend
- `DEBUG`: Enable SQLAlchemy echo

## Adding New Features

1. **Model**: Create in [src/models/](src/models/) inheriting `Base`, import in [database.py](src/core/database.py) `init_db()`
2. **Schema**: Create Pydantic models in [src/schemas/](src/schemas/)
3. **Repository**: Extend `BaseRepository` in [src/repositories/](src/repositories/)
4. **Service**: Business logic in [src/services/](src/services/)
5. **Route**: FastAPI router in [src/api/](src/api/), register in [src/api/__init__.py](src/api/__init__.py)
