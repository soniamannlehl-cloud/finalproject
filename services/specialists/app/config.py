"""
Specialists service configuration.

Data-provider settings are declared as ordered chains rather than single
values: each data class names a primary and a fallback, so provider failure
is a configured degradation path rather than an exception. See
app/common/tool_client.py (M2+) for the retry/breaker/failover logic.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- service ---
    service_name: str = "specialists"
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8081

    # Advertised in every AgentCard so the Director knows where to send tasks.
    public_base_url: str = "http://specialists:8081"

    # --- data providers -----------------------------------------------------
    # yfinance requires no key, which is why it anchors the fallback chain:
    # the platform stays demonstrable even with zero paid API keys configured.
    fmp_api_key: str = ""
    newsapi_key: str = ""
    tavily_api_key: str = ""
    polygon_api_key: str = ""
    # SEC EDGAR rejects requests (403) whose User-Agent lacks contact
    # information. The format must identify the requester and provide a way to
    # reach them; a bare product name is not accepted.
    sec_user_agent: str = "AI Investment Research Platform academic-project@example.com"

    # --- resilience ---------------------------------------------------------
    provider_timeout_s: int = 20
    provider_max_retries: int = 3
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_s: int = 60

    # Immutable artifacts (filings, reported statements) are cached
    # indefinitely; only volatile data expires. This is what makes repeated
    # demo runs on the same ticker nearly free.
    cache_ttl_market_data_s: int = 300
    cache_ttl_news_s: int = 3600
    cache_ttl_immutable_s: int = 0  # 0 == never expire

    # --- LLM (one interpretation call per specialist, cheap tier) ---
    openai_api_key: str = ""
    model_interpretation: str = "gpt-4o-mini"
    temperature: float = 0.0

    # --- observability ---
    otel_exporter_otlp_endpoint: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
