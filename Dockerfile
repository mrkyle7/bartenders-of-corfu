# Multi-stage build for installing dependencies
FROM python:3.13-slim

LABEL Maintainer="Kyle and Dan"

WORKDIR /app

# Copy only the dependency files first for better caching

COPY requirements.txt ./

# Install dependencies
RUN pip install -r requirements.txt

# Copy the rest of the app
COPY src .
COPY static ./static

EXPOSE 8000

RUN useradd app
USER app

CMD ["python", "bartenders-of-corfu/server.py"]