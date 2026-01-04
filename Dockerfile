# Multi-stage build for installing dependencies
FROM python:3.14-slim

LABEL Maintainer="Kyle and Dan"

WORKDIR /app

# Copy only the dependency files first for better caching

COPY requirements.txt ./

RUN apt-get update
RUN apt-get install -y gcc g++

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY log_conf.yaml .
COPY app ./app
COPY static ./static

EXPOSE 8000

RUN useradd app
USER app

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "log_conf.yaml"]
