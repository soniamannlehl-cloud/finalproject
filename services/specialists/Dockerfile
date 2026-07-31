# ============================================================================
# Specialists service -- data plane (A2A + data providers)
# ============================================================================
# Build context is the REPO ROOT. See docker-compose.yml.
# ============================================================================
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages/contracts /packages/contracts
RUN pip install --no-cache-dir /packages/contracts

COPY services/specialists/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/specialists/app ./app

EXPOSE 8081

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8081/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
