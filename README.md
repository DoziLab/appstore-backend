# App Store Backend

A FastAPI-based backend for managing deployments on Openstack.

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)

### 1. Clone and Setup

```bash
git clone <repository-url>
cd appstore-backend
```

### 2. Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

### 3. Start with Docker (Recommended)

```bash
docker compose up -d
```

This starts:
- **API** at http://localhost:8000
- **PostgreSQL** at localhost:5432
- **Redis** at localhost:6379
- **Celery Worker** for async tasks

### 4. Verify Installation

```bash
# Health check
curl http://localhost:8000/health

# API documentation
open http://localhost:8000/docs
```

## Local Development (without Docker)

### 1. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 3. Start Services

Make sure PostgreSQL and Redis are running locally, then:

```bash
uvicorn src.main:app --reload
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/docs` | Swagger UI |
| GET | `/api/v1/deployments` | List deployments |
| POST | `/api/v1/deployments` | Create deployment |

## Project Structure

```
src/
├── main.py                # FastAPI Entrypoint
├── celery_app.py          # Celery Configuration
│
├── api/                   # API Routes
│   └── deployments.py     # Deployment endpoints
│
├── core/                  # Core Configuration
│   ├── config.py          # Environment Settings
│   ├── database.py        # DB Session Management
│   └── dependencies.py    # FastAPI Dependencies
│
├── models/                # SQLAlchemy Models
│   └── deployment.py      # Deployment Model
│
├── schemas/               # Pydantic Schemas
│   └── deployment.py      # Request/Response Validation
│
├── services/              # Business Logic
│   └── deployment_service.py
│
├── repositories/          # Database Access Layer
│   └── deployment_repository.py
│
└── tasks/                 # Celery Tasks
    ├── deploy_tasks.py
    └── sync_tasks.py
```

## Useful Commands

```bash
# View logs
docker compose logs -f api

# Rebuild after code changes
docker compose up -d --build

# Stop all services
docker compose down

# Reset database (deletes all data!)
docker compose down -v
```
