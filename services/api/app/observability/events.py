"""
Structured run logging for observability.

Emits JSON-shaped log lines that are easy to grep and correlate with
LangSmith traces when LANGSMITH_API_KEY is configured.
"""

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("irp.workflow")


def log_event(run_id: str, stage: str, **fields) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stage": stage,
        **fields,
    }
    log.info(json.dumps(payload, default=str))
