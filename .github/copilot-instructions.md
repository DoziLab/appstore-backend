# App Store Backend - Copilot Instructions

## Project Overview

This repository is part of a **student project** that implements a **Teaching App Store for OpenStack**.

The goal of the project is to provide a **web-based App Store** that allows lecturers to deploy and manage teaching environments (VMs, lab setups, Kubernetes clusters, etc.) on **OpenStack** without requiring deep infrastructure knowledge.

The App Store abstracts OpenStack complexity and provides:
- reusable **application templates**
- automated **deployment orchestration**
- controlled **resource usage**
- strong **governance, security, and observability**

The system is designed to be **realistically operable in a university environment (DHBW)** and potentially reusable across multiple locations.

---

## Problem We Are Solving

OpenStack is powerful but complex and not suitable for non-technical lecturers.

Typical pain points today:
- manual VM creation
- copy-paste scripts
- long setup times per VM
- missing overview of running environments
- poor error feedback
- no clean approval or reuse of templates

This project replaces that with:
- **one-click deployments**
- **versioned templates**
- **course- and group-based environments**
- **clear status feedback**
- **admin approval workflows**
- **central monitoring & logging**

---

## Target Users (Personas)

The system is designed around the following user personas :contentReference[oaicite:1]{index=1}:

### Lecturers (Primary Users)
- May have **no IT knowledge** or **advanced IT knowledge**
- Want to deploy environments quickly and reliably
- Should not need to understand OpenStack, SSH, IPs, or networking
- Expect clear deployment status and easy reset/redeploy options

### Students (End Users)
- Do not deploy infrastructure themselves
- Access environments via browser, SSH, or Guacamole
- Want stable environments with minimal setup steps

### App Store Admins
- Approve templates before they become public
- Monitor system health, failures, and usage
- Support lecturers when deployments fail
- Require good logging, metrics, and traceability

### OpenStack Infrastructure Admins
- Maintain OpenStack itself
- Define quotas and policies
- Require secure API usage
- Must retain OpenStack as the single source of truth

---

## High-Level Summary
The App Store **does not replace OpenStack**, it **orchestrates it**.

---

## Core Domain Concepts

When writing code, keep these concepts in mind:

- **Template**
  - Describes *what* can be deployed
  - Has versions
  - May reference artifacts (Heat, cloud-init, Ansible, Helm)
  - Must be approved before public use

- **Deployment**
  - Concrete instantiation of a template
  - Belongs to a lecturer and optionally a course
  - Can target:
    - per course
    - per group
    - per student

- **Deployment Instance**
  - A concrete VM or service created by a deployment
  - Has access endpoints (web, SSH, Guacamole, etc.)

- **Course**
  - Logical teaching unit
  - Used for grouping deployments, cleanup, permissions

- **OpenStack Project**
  - Typically one project per lecturer
  - Quotas enforced at project level
  - Courses are mapped to Heat stacks, not separate projects

---

## Design & Coding Principles

When generating code, always follow these principles:

- **Separation of Concerns**
  - API layer: routing only
  - Service layer: business logic
  - Repository layer: persistence only
  - Core layer: cross-cutting concerns (auth, logging, responses)

- **Security First**
  - Never store secrets or passwords in plain text
  - Never log credentials, tokens, or SSH keys
  - Use secret references instead of secret values

- **Robustness**
  - Long-running tasks must be asynchronous
  - Failures must be traceable via logs and IDs
  - No silent failures

- **OpenStack as Source of Truth**
  - Do not duplicate OpenStack state unnecessarily
  - Cache only when required for performance

- **Governance**
  - Templates can be private, tenant-public, or global
  - Public templates require approval and auditability

---

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

## Code Style & Cleanliness Guidelines

- Language consistency
  - Match the existing file’s language (ENGLISH) and idioms; do not mix languages in a file.
  - Respect architecture boundaries: API → Service → Repository → Model/DB; async work in Tasks.
  - All code, comments, docstrings, logs, and error messages must be in English.
  - Do not use emojis or decorative symbols in code or comments.

- Python & FastAPI conventions
  - Follow PEP8. Format with black; order imports with isort (stdlib → third‑party → local).
  - Use type hints everywhere with explicit return types. Avoid `Any` unless necessary.
  - Keep routes thin: use dependency injection (DBSession, RequestID, Pagination) and delegate to services.
  - Always return via ResponseBuilder (`success`, `created`, `paginated`) and include `request_id`.
  - Do not create SQLAlchemy sessions manually; accept `db` from DI and pass to services/repositories.

- Services & Repositories
  - Put business logic in services; repositories encapsulate DB access only.
  - Extend `BaseRepository[T]`; prefer its CRUD methods over ad‑hoc session calls.
  - Keep methods small, single‑purpose, and free of hidden side effects.

- Schemas (Pydantic v2)
  - Set `model_config = {"from_attributes": True}` for ORM compatibility.
  - Naming: `*Create`, `*Update`, `*Response`. Use snake_case fields. Avoid exposing internal details.

- Tasks (Celery)
  - Trigger async work via `.delay()` and pass only serializable identifiers (e.g., IDs).
  - Tasks must be idempotent; never pass DB sessions into tasks.

- Errors, logging, and configuration
  - Raise domain exceptions in services; map to HTTP in API routes. Include `request_id` in logs.
  - Read settings via `src/core/config.py`; never hardcode secrets, URLs, or credentials.

- Testing
  - Use pytest. Prefer unit tests for services/repositories and API tests for routes.
  - Keep tests isolated and deterministic; assert ResponseBuilder output shapes.

- Performance & security
  - Use pagination for list endpoints; validate inputs; avoid N+1 queries.
  - Never log credentials or PII; sanitize data from external sources.

- Commenting (efficient, intent-driven)
  - Comment the “why”, intent, assumptions, constraints, and non-obvious trade-offs; avoid restating what the code does.
  - Prefer clearer names, smaller functions, and types over explanatory comments.
  - Use docstrings for public modules/classes/functions:
    - Start with a one-sentence summary; add context, params, return types, and exceptions raised.
  - Place comments above the code they describe; avoid long trailing inline comments.
  - Maintain comments: update with code changes; remove obsolete or misleading notes.
  - Error and log messages must be actionable, precise, consistent, include request_id, and never expose secrets or PII.

## Final Note

This project is not a demo or toy system.
It is designed as a **realistic teaching platform** that could be adopted by a university.

Code should reflect that level of care.