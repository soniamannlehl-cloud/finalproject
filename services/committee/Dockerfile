# ============================================================================
# Committee service -- deliberation (CrewAI)
# ============================================================================
# Build context is the REPO ROOT. See docker-compose.yml.
#
# This image intentionally contains NO LangGraph -- not because the two
# cannot coexist (they can; this was measured), but because keeping CrewAI's
# ~1.3GB dependency tree out of the control plane keeps that image at ~530MB
# and its rebuilds fast. The /health endpoint asserts langgraph's absence so
# an accidental dependency leak fails loudly rather than silently bloating
# the image.
# ============================================================================
FROM python:3.11-slim

# CrewAI pulls packages with native extensions (tokenizers, chroma) that
# need a compiler when a wheel isn't available for the platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages/contracts /packages/contracts
RUN pip install --no-cache-dir /packages/contracts

COPY services/committee/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/committee/app ./app

EXPOSE 8082

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8082/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
