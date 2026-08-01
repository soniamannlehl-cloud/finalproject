"""
Unified tool client with retry, simple cache, and circuit breaker.

Specialist tools call through here so provider failures degrade
predictably instead of crashing agents.
"""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings

log = logging.getLogger(__name__)
T = TypeVar("T")

_cache: dict[str, tuple[float, object]] = {}
_circuit: dict[str, tuple[int, float]] = {}


class CircuitOpenError(RuntimeError):
    """Provider circuit breaker is open after repeated failures."""


def _cache_key(provider: str, operation: str, *args) -> str:
    return f"{provider}:{operation}:{':'.join(str(a) for a in args)}"


def _check_circuit(provider: str) -> None:
    settings = get_settings()
    state = _circuit.get(provider)
    if not state:
        return
    failures, opened_at = state
    if failures >= settings.circuit_breaker_failure_threshold:
        if time.time() - opened_at < settings.circuit_breaker_reset_s:
            raise CircuitOpenError(f"circuit open for {provider}")
        _circuit.pop(provider, None)


def _record_failure(provider: str) -> None:
    settings = get_settings()
    failures, _ = _circuit.get(provider, (0, time.time()))
    _circuit[provider] = (failures + 1, time.time())
    if failures + 1 >= settings.circuit_breaker_failure_threshold:
        log.warning("circuit breaker opened for %s", provider)


def _record_success(provider: str) -> None:
    _circuit.pop(provider, None)


def call_with_resilience(
    provider: str,
    operation: str,
    fn: Callable[[], T],
    *,
    cache_ttl_s: int | None = None,
    use_cache: bool = True,
) -> T:
    """
    Execute a provider call with retry, cache, and circuit breaker.

    Raises the underlying exception after retries are exhausted so callers
    can fall back to the next provider in the chain.
    """
    settings = get_settings()
    key = _cache_key(provider, operation)

    if use_cache and cache_ttl_s is not None:
        cached = _cache.get(key)
        if cached and time.time() - cached[0] < cache_ttl_s:
            return cached[1]  # type: ignore[return-value]

    _check_circuit(provider)

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(settings.provider_max_retries),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _execute() -> T:
        return fn()

    try:
        result = _execute()
        _record_success(provider)
        if use_cache and cache_ttl_s is not None:
            _cache[key] = (time.time(), result)
        return result
    except Exception:
        _record_failure(provider)
        raise
