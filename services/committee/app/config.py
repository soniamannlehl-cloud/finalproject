"""
Committee service configuration.

This service is stateless and deliberately expensive-but-bounded: it is the
only place frontier-model debate happens, so its cost controls live here.
It receives a condensed evidence brief -- never raw filings or article text
-- which is the single largest lever on total run cost.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- service ---
    service_name: str = "committee"
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8082
    public_base_url: str = "http://committee:8082"

    # --- LLM -----------------------------------------------------------------
    # Adversarial debate is the one workload here that genuinely needs a
    # capable model: a weak Bear Analyst produces a strawman, which makes the
    # CIO's synthesis worthless.
    openai_api_key: str = ""
    model_bull: str = "gpt-4o-mini"
    model_bear: str = "gpt-4o-mini"
    model_cio: str = "gpt-4o"
    temperature: float = 0.2  # slight variation so Bull/Bear don't converge

    # --- cost controls -------------------------------------------------------
    max_debate_rounds: int = 1
    max_brief_claims: int = 40  # cap on evidence passed into the debate
    request_timeout_s: int = 180

    # --- observability ---
    otel_exporter_otlp_endpoint: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
