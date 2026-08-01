"""
HTTP client for the CrewAI committee service.

Mirrors the specialist A2A client pattern: transport failures become
structured error results rather than raised exceptions, so a committee
outage degrades the run instead of crashing mid-checkpoint.
"""

import logging
import time
from datetime import datetime, timezone

import httpx
from contracts import TaskState

from ..config import get_settings

log = logging.getLogger(__name__)


class CommitteeClient:
    """Dispatch deliberation requests to the committee service."""

    def __init__(self, base_url: str | None = None, timeout_s: int | None = None):
        settings = get_settings()
        self._base_url = (base_url or settings.committee_url).rstrip("/")
        self._timeout_s = timeout_s or 180

    async def deliberate(
        self,
        brief: dict,
        run_id: str,
        traceparent: str | None = None,
    ) -> dict:
        """
        Convene the investment committee.

        Always returns a dict with at least `state` and either committee output
        or an `error` field — never raises on transport failure.
        """
        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        def _failed(error: str) -> dict:
            return {
                "state": TaskState.FAILED.value,
                "error": error,
                "action": "insufficient_evidence",
                "confidence": 0.0,
                "cio_rationale": f"Committee unavailable: {error}",
                "bull_case": {"role": "bull_analyst", "argument": "", "conviction": 0.0, "claim_ids": []},
                "bear_case": {"role": "bear_analyst", "argument": "", "conviction": 0.0, "claim_ids": []},
                "started_at": started.isoformat(),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }

        endpoint = f"{self._base_url}/a2a/tasks"
        payload = {
            "task_id": f"committee-{run_id}",
            "run_id": run_id,
            "capability": "committee.deliberate",
            "inputs": {"brief": brief},
            "traceparent": traceparent,
        }

        try:
            headers = {"traceparent": traceparent} if traceparent else {}
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                result = resp.json()
                result.setdefault("state", TaskState.SUCCEEDED.value)
                result["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                return result
        except httpx.TimeoutException:
            log.warning("committee deliberation timed out after %ds", self._timeout_s)
            return _failed(f"timeout after {self._timeout_s}s")
        except Exception as e:  # noqa: BLE001
            log.warning("committee deliberation failed: %s", e)
            return _failed(f"transport error: {e}")


_client: CommitteeClient | None = None


def get_committee_client() -> CommitteeClient:
    global _client
    if _client is None:
        _client = CommitteeClient()
    return _client
