# server/Dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# Useful system deps for “wait-for”, SSL, tz, and building the odd wheel
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tzdata netcat-traditional gcc \
    && rm -rf /var/lib/apt/lists/*

# (Optional) if you want non-root
RUN useradd -m appuser
USER appuser

COPY --chown=appuser:appuser requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser . .

EXPOSE 7123