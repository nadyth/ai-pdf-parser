# syntax=docker/dockerfile:1.7

# ── Stage 1: builder ────────────────────────────────────────────────────────
# Installs uv + project dependencies into /app/.venv. curl is only needed here.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml README.md ./
RUN uv sync --no-dev

# ── Stage 2: runtime ────────────────────────────────────────────────────────
# Clean slim base. No apt packages installed at all — pypdfium2 + asyncpg
# + pdfplumber all ship prebuilt manylinux wheels.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    STORAGE_ROOT=/data/storage

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN mkdir -p /data/storage

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
