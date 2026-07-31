# ============================================================================
# API service -- control plane (LangGraph + FastAPI)
# ============================================================================
# Build context is the REPO ROOT, not this directory, so the shared contracts
# package can be copied in. See docker-compose.yml.
# ============================================================================
FROM python:3.11-slim

# WeasyPrint renders the PDF report and links against the system Pango/Cairo
# stack; without these the import succeeds but rendering fails at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Shared contracts first -- it changes least often, so this layer stays cached
# across most rebuilds.
COPY packages/contracts /packages/contracts
RUN pip install --no-cache-dir /packages/contracts

COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/api/app ./app

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
