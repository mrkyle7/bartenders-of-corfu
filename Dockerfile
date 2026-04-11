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
COPY playtesting ./playtesting

EXPOSE 8080

RUN useradd app
USER app

ENV PATH="/app/.venv/bin:$PATH"
# Cloud Run injects PORT=8080. Fall back to 8080 for local runs too so the
# Dockerfile is portable across Cloud Run and k3s/docker-compose.
ENV PORT=8080

# Shell form so ${PORT} is expanded at container start
CMD uvicorn app.api:app --host 0.0.0.0 --port ${PORT} --log-config log_conf.yaml
