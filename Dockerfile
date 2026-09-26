# Multi-stage Dockerfile for TimeInvestor
# Stage 1: Build React 19 / Vite frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

# Install dependencies using package-lock.json for deterministic builds
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy frontend source code and compile production assets to dist/
COPY frontend/ ./
RUN npm run build

# Stage 2: Lightweight Python 3.12 runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNNING_IN_DOCKER=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# Install curl for container HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user and group for security isolation
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Install backend dependencies without caching
# Exact versions from the lock (generated from requirements.txt's ranges with
# `uv pip compile --universal`, so the same file is valid on Linux and Windows).
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# Copy application backend, execution scripts, and launcher
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY run.py ./

# Copy compiled frontend from Stage 1 into backend's expected static distribution path
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Create SQLite database directory and assign ownership to appuser
RUN mkdir -p /app/backend/database && chown -R appuser:appgroup /app

# Run as non-root user
USER appuser

EXPOSE 8000

# Container healthcheck against FastAPI /api/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start TimeInvestor with production settings
CMD ["python", "run.py", "--no-browser", "--host", "0.0.0.0", "--port", "8000"]
