# Multi-stage build for installing dependencies
FROM python:3.14-slim AS builder

LABEL Maintainer="Kyle and Dan"

WORKDIR /app

RUN apt-get update
RUN apt-get install -y gcc g++

# Copy only the dependency files first for better caching

COPY pyproject.toml ./

ENV UV_NO_DEV=1

# Install dependencies
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    uv sync

FROM python:3.14-slim
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Copy the rest of the app
COPY log_conf.yaml .
COPY app ./app
COPY static ./static

EXPOSE 8000

RUN useradd app
USER app

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "log_conf.yaml"]
