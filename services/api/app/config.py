"""
API service configuration.

Model tiering lives here rather than being scattered across agent modules,
so cost/quality can be retuned without touching logic. The principle: pay
frontier-model prices only where a reasoning error would poison everything
downstream (planning, thesis synthesis, hallucination detection), and use
the cheap tier everywhere else.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- service ---
    service_name: str = "api"
    environment: str = "development"
    log_level: str = "INFO"

    # --- database (checkpointer + evidence repository) ---
    database_url: str = "postgresql://irp:irp@postgres:5432/irp"

    # --- downstream services (A2A) ---
    specialists_url: str = "http://specialists:8081"
    committee_url: str = "http://committee:8082"
    a2a_timeout_s: int = 120

    # --- LLM providers ---
    openai_api_key: str = ""

    # --- model tiering ------------------------------------------------------
    # CHEAP: high call volume, low judgment requirement.
    model_cheap: str = "gpt-4o-mini"
    # STRONG: errors here corrupt every downstream stage.
    model_strong: str = "gpt-4o"

    # Role -> tier assignment. Planner and one-line thesis polish use the cheap
    # tier because industry selection is deterministic and the thesis stance is
    # already computed from signals. Semantic safety still gets the strong tier.
    model_planner: str = "cheap"
    model_validator: str = "cheap"
    model_thesis: str = "cheap"
    model_safety_semantic: str = "strong"
    model_report_prose: str = "cheap"

    temperature: float = 0.0

    # --- workflow limits ----------------------------------------------------
    # Every loop in the graph is capped. An uncapped replan or retry cycle can
    # hang a live demo and burn budget with nothing to show for it.
    max_replan_rounds: int = 2
    max_task_retries: int = 2
    max_safety_reresearch_rounds: int = 1
    max_brief_claims: int = 40

    # --- observability ---
    langsmith_api_key: str = ""
    langsmith_project: str = "investment-research-platform"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_tracing: bool = True
    otel_exporter_otlp_endpoint: str = ""

    def resolve_model(self, role: str) -> str:
        """Map a role name to a concrete model id via its configured tier."""
        tier = getattr(self, f"model_{role}", "cheap")
        return self.model_strong if tier == "strong" else self.model_cheap


@lru_cache
def get_settings() -> Settings:
    return Settings()
