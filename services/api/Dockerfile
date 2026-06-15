# Multi-stage build for WhatsApp Marketing API

# Stage 1: Build stage
FROM python:3.12-slim as builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# Copy project files
COPY . .
RUN uv sync --no-dev


# Stage 2: Production stage
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Create non-root user
RUN addgroup --system django && \
    adduser --system --ingroup django django

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy project files
COPY --chown=django:django . .

# Create staticfiles and media directories with correct ownership
RUN mkdir -p /app/staticfiles /app/media/media_assets && \
    chown -R django:django /app/staticfiles /app/media

# Switch to non-root user BEFORE collectstatic
USER django

# Collect static files (now runs as django user, so files are owned by django)
RUN python manage.py collectstatic --no-input

# Expose port
EXPOSE 8000

# Run the application via Daphne (ASGI) — required for Django Channels WebSocket support.
# Daphne handles both HTTP and WS on the same port.
CMD ["sh", "-c", "daphne -b 0.0.0.0 -p ${PORT:-8000} core.asgi:application"]
