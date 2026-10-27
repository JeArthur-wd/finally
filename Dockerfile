# ---------- Stage 1: build the Next.js static export ----------
FROM node:22-slim AS frontend
WORKDIR /app/frontend

# Install dependencies first so this layer is cached until the lockfile changes
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
# Output: /app/frontend/out


# ---------- Stage 2: Python runtime ----------
FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app/backend

# Dependencies only (cached until pyproject.toml / uv.lock change)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application source, then install the project itself
COPY backend/ ./
RUN uv sync --frozen --no-dev

# Frontend static export
COPY --from=frontend /app/frontend/out /app/backend/static

ENV PATH="/app/backend/.venv/bin:$PATH" \
    DB_PATH=/app/db/finally.db \
    STATIC_DIR=/app/backend/static

RUN mkdir -p /app/db
VOLUME ["/app/db"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
