FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY src/ ./src/
COPY tests/ ./tests/

# Install Python dependencies (including dev extras for running tests inside container)
RUN pip install --no-cache-dir ".[dev]"

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
