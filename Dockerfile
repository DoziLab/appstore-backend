FROM python:3.11-slim

WORKDIR /app

# Install system dependencies + Ansible
RUN apt-get update && apt-get install -y \
    gcc \
    ansible \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY src/ ./src/
COPY tests/ ./tests/

# Install Python dependencies
RUN uv sync --frozen --extra dev

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
