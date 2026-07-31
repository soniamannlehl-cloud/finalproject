"""
A2A client -- the control plane's sole route to the specialist fleet.

Two responsibilities:

  DISCOVERY  fetch AgentCards, build a capability -> endpoint index. The
             Planner names capabilities; this is the only component that
             knows which agent serves them or where it lives.

  DISPATCH   send an A2ATaskRequest, return an A2ATaskResult. Transport
             failures are converted into FAILED results rather than raised,
             so a specialist outage degrades a run instead of crashing the
             workflow mid-checkpoint.

The registry is refreshed lazily and on dispatch failure, so a specialist
restart does not require an API restart.
"""

import logging
import time
from datetime import datetime, timezone

import httpx
from contracts import A2ATaskRequest, A2ATaskResult, TaskState

from ..config import get_settings

log = logging.getLogger(__name__)


class A2AClient:
    """Discovery + dispatch against one or more specialist services."""

    def __init__(self, base_urls: list[str] | None = None, timeout_s: int | None = None):
        settings = get_settings()
        self._base_urls = base_urls or [settings.specialists_url]
        self._timeout_s = timeout_s or settings.a2a_timeout_s
        # capability -> (agent_name, task_endpoint)
        self._index: dict[str, tuple[str, str]] = {}
        self._discovered = False

    # -- discovery ----------------------------------------------------------

    async def discover(self, force: bool = False) -> dict[str, tuple[str, str]]:
        """
        Build the capability index from published AgentCards.

        A service that is down at discovery time is logged and skipped rather
        than fatal: the platform should start and report missing capabilities
        as declared gaps, not refuse to boot.
        """
        if self._discovered and not force:
            return self._index

        index: dict[str, tuple[str, str]] = {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            for base in self._base_urls:
                try:
                    resp = await client.get(f"{base}/a2a/agents")
                    resp.raise_for_status()
                    payload = resp.json()
                except Exception as e:  # noqa: BLE001
                    log.warning("A2A discovery failed for %s: %s", base, e)
                    continue

                for card in payload.get("agents", []):
                    endpoint = self._task_endpoint(card, base)
                    for skill in card.get("skills", []):
                        capability = skill.get("id")
                        if capability:
                            index[capability] = (card.get("name", "unknown"), endpoint)

        self._index = index
        self._discovered = True
        log.info("A2A discovery: %d capabilities across %d service(s)", len(index), len(self._base_urls))
        return index

    @staticmethod
    def _task_endpoint(card: dict, fallback_base: str) -> str:
        """
        Resolve the task URL from the card's advertised interface.

        Falls back to the service base URL when a card omits it, so a
        partially-specified card degrades rather than breaking dispatch.
        """
        for iface in card.get("supported_interfaces", []):
            url = iface.get("url")
            if url:
                return url.rstrip("/").removesuffix("/a2a") + "/a2a/tasks"
        return f"{fallback_base}/a2a/tasks"

    async def capabilities(self) -> set[str]:
        return set((await self.discover()).keys())

    async def missing(self, required: set[str]) -> set[str]:
        """Capabilities no discovered agent can serve -- reported as declared gaps."""
        return required - await self.capabilities()

    # -- dispatch -----------------------------------------------------------

    async def dispatch(
        self,
        capability: str,
        inputs: dict,
        run_id: str,
        task_id: str,
        attempt: int = 1,
        traceparent: str | None = None,
    ) -> A2ATaskResult:
        """
        Execute one capability on whichever agent advertises it.

        Always returns an A2ATaskResult -- never raises. The Director needs
        to distinguish "agent ran and found nothing" from "agent unreachable",
        and both must be recordable rather than fatal.
        """
        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        def _failed(error: str, agent: str = "unresolved") -> A2ATaskResult:
            return A2ATaskResult(
                task_id=task_id,
                run_id=run_id,
                agent_id=agent,
                capability=capability,
                state=TaskState.FAILED,
                error=error,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        index = await self.discover()
        if capability not in index:
            # Re-discover once: the fleet may have started after we did.
            index = await self.discover(force=True)
        if capability not in index:
            return _failed(f"no agent advertises capability '{capability}'")

        agent_name, endpoint = index[capability]
        request = A2ATaskRequest(
            task_id=task_id,
            run_id=run_id,
            capability=capability,
            inputs=inputs,
            timeout_s=self._timeout_s,
            attempt=attempt,
            traceparent=traceparent,
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                headers = {"traceparent": traceparent} if traceparent else {}
                resp = await client.post(
                    endpoint, json=request.model_dump(mode="json"), headers=headers
                )
                resp.raise_for_status()
                return A2ATaskResult.model_validate(resp.json())
        except httpx.TimeoutException:
            log.warning("A2A timeout: %s -> %s", capability, endpoint)
            self._discovered = False  # force rediscovery next call
            return _failed(f"timeout after {self._timeout_s}s", agent_name)
        except Exception as e:  # noqa: BLE001
            log.warning("A2A dispatch failed: %s -> %s: %s", capability, endpoint, e)
            self._discovered = False
            return _failed(f"transport error: {e}", agent_name)


_client: A2AClient | None = None


def get_a2a_client() -> A2AClient:
    """Process-wide client so the discovery index is shared across requests."""
    global _client
    if _client is None:
        _client = A2AClient()
    return _client
