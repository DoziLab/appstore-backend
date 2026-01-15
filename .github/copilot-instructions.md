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

The system is designed around the following user personas:

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

### Core Settings
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: PostgreSQL connection
- `REDIS_URL`: Celery broker/backend (format: `redis://host:port/db`)
- `DEBUG`: Enable SQLAlchemy echo and verbose logging

### OpenStack Integration
- `OPENSTACK_AUTH_URL`: OpenStack Keystone endpoint
- `OPENSTACK_PROJECT_NAME`: Project/tenant name
- `OPENSTACK_PROJECT_DOMAIN_NAME`: Project domain (typically `default`)
- `OPENSTACK_USERNAME`: OpenStack admin username
- `OPENSTACK_PASSWORD`: OpenStack admin password
- `OPENSTACK_USER_DOMAIN_NAME`: User domain (typically `default`)
- `OPENSTACK_REGION_NAME`: Target region (e.g., `RegionOne`)

Alternatively, configure via `~/.config/openstack/clouds.yaml` and set `OPENSTACK_CLOUD=<cloud-name>`.

### Logging & Observability
- `LOG_LEVEL`: Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`)

### Seed Data (Development)
- `SEED_ON_STARTUP`: Auto-seed demo data when container starts (default: `false`)
- `ADMIN_EMAIL`, `ADMIN_PASSWORD`: Default admin credentials for seed data

---

## Development Environment

### Codespace & Devcontainer
The project includes a complete Devcontainer configuration in [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json):

**Pre-installed Extensions:**
- Python, Pylance, Ruff, Black Formatter
- PostgreSQL, REST Client (Bruno)
- Docker, YAML

**Automatic Setup:**
- Docker Compose starts PostgreSQL, Redis, API, Celery Worker on container creation
- Database is auto-migrated via Alembic
- Optional seed data is loaded if `SEED_ON_STARTUP=true`

**Port Forwarding:**
- `8000`: FastAPI application
- `5432`: PostgreSQL
- `6379`: Redis

### OpenStack Setup
The system interacts with OpenStack via the `openstacksdk` library.

**Service Layer:**
- [`src/services/openstack_service.py`](src/services/openstack_service.py): OpenStack client wrapper
- Heat orchestration for stack deployments
- Keystone project/user management
- Neutron network operations

**Configuration:**
- Use `clouds.yaml` for multi-environment support (dev, staging, prod)
- Store credentials in environment variables or OpenStack config files
- Never commit `clouds.yaml` or credentials to Git

**Testing OpenStack Connectivity:**
```bash
openstack --os-cloud=<cloud-name> server list
```

### Seed Data & Initialization
[`scripts/seed_data.py`](scripts/seed_data.py) creates demo data for local development:

**Created Entities:**
- Admin user with full permissions
- Sample templates (Ubuntu VM, Kubernetes cluster, etc.)
- Template versions with Heat YAML files
- Sample courses and OpenStack projects

**Manual Seeding:**
```bash
python -m scripts.seed_data
```

**Automatic Seeding:**
Set `SEED_ON_STARTUP=true` in `.env` for container auto-seed.

### Scripts & Utilities
The [`scripts/`](scripts/) directory contains helper tools:

- `seed_data.py`: Demo data initialization
- `test_auth.sh`: Keycloak token acquisition test
- `add_dozilab_dashboard_template.py`: Add specific template
- `create-server.sh`, `create-github-runner-vm.sh`: OpenStack VM provisioning

---

## Testing Strategy

### Test Organization
```
tests/
├── api/              # FastAPI route tests (HTTP layer)
├── unit/             # Service & repository tests (isolated)
├── integrations/     # OpenStack integration tests (optional)
└── fixtures/         # Shared test data and mocks
```

### Running Tests
```bash
pytest                              # All tests
pytest tests/api/                   # API tests only
pytest tests/unit/                  # Unit tests only
pytest -v --cov=src --cov-report=html  # With coverage
```

### Mocking OpenStack
For unit tests, mock OpenStack SDK calls to avoid external dependencies:
```python
from unittest.mock import patch

@patch('src.services.openstack_service.OpenStackService.create_stack')
def test_deploy(mock_create_stack, db_session):
    mock_create_stack.return_value = {'id': 'stack-123', 'status': 'CREATE_IN_PROGRESS'}
    # Test logic here
```

For integration tests, use a real or test OpenStack instance.

### Test Fixtures
Define reusable fixtures in [`tests/conftest.py`](tests/conftest.py):
- `db_session`: Test database session
- `client`: TestClient for FastAPI
- Sample models (users, templates, courses)

---

## Troubleshooting

### Common Issues

**Port Conflicts**
```bash
# Check if ports 8000, 5432, 6379 are in use
lsof -i :8000
# Kill process or change port in docker-compose.yml
```

**OpenStack Connection Timeouts**
- Verify `OPENSTACK_AUTH_URL` is reachable
- Check credentials in `.env` or `clouds.yaml`
- Test with: `openstack --os-cloud=<cloud> server list`

**Celery Worker Not Starting**
- Check Redis connection: `redis-cli -u $REDIS_URL ping`
- Verify worker logs: `docker compose logs celery-worker`
- Restart worker: `docker compose restart celery-worker`

**Database Migration Failures**
```bash
# Reset database (⚠️ destroys data)
docker compose down -v
docker compose up -d db
alembic upgrade head
```

**Import Errors After New Dependencies**
```bash
# Rebuild container after pyproject.toml changes
docker compose build api celery-worker
docker compose up -d
```

**Seed Data Already Exists**
- Drop and recreate database, or
- Manually delete conflicting records before seeding

### Debugging in VS Code
Launch configurations in [`.vscode/launch.json`](.vscode/launch.json):
- **Debug FastAPI**: Attach to running Uvicorn server
- **Debug Celery Task**: Attach to Celery worker process

**Enable Debug Logging:**
```bash
export LOG_LEVEL=DEBUG
export DEBUG=true
```

---

## Adding New Features

1. **Model**: Create in [src/models/](src/models/) inheriting `Base`, import in [database.py](src/core/database.py) `init_db()`
2. **Migration**: Generate Alembic migration: `alembic revision --autogenerate -m "description"`
3. **Schema**: Create Pydantic models in [src/schemas/](src/schemas/) (`*Create`, `*Update`, `*Response`)
4. **Repository**: Extend `BaseRepository` in [src/repositories/](src/repositories/)
5. **Service**: Business logic in [src/services/](src/services/)
6. **Route**: FastAPI router in [src/api/](src/api/), register in [src/api/__init__.py](src/api/__init__.py)
7. **Tests**: 
   - Unit tests in [tests/unit/](tests/unit/) for services/repositories
   - API tests in [tests/api/](tests/api/) for routes
8. **Bruno**: Add API requests in [bruno/](bruno/) for manual testing and documentation
9. **Apply Migration**: Run `alembic upgrade head` or restart Docker containers

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

- TODO Comments
  - Use the exact format: `# TODO: Description of what needs to be done`
  - Start with `# TODO:` (space after colon) on its own line above the relevant code
  - Write clear, actionable descriptions in English
  - Include context with explanatory comments below the TODO if needed
  - Example format:
    ```python
    # TODO: Implement rate limiting per user based on their role
    # Current implementation applies global rate limit to all endpoints
    current_user = get_current_user()
    ```
  - Keep TODOs visible and trackable; remove or update them when completed
  - Never use TODO for critical security issues; fix those immediately

- Documentation
  DO NOT create documentations unless explicitly requested.

## Final Note

This project is not a demo or toy system.
It is designed as a **realistic teaching platform** that could be adopted by a university.

Code should reflect that level of care.