"""
LangSmith observability setup.

Must run BEFORE LangGraph is imported so tracing hooks attach correctly.
LangSmith UI expects these env vars (see smith.langchain.com project setup):
  LANGSMITH_TRACING=true
  LANGSMITH_ENDPOINT=https://api.smith.langchain.com
  LANGSMITH_API_KEY=...
  LANGSMITH_PROJECT=investment-research-platform
"""

import logging
import os

log = logging.getLogger(__name__)


def configure_langsmith() -> bool:
    """
    Enable LangSmith tracing if configured.

    Returns True when tracing is active.
    """
    from ..config import get_settings

    settings = get_settings()
    if not settings.langsmith_api_key:
        log.info("LangSmith tracing disabled (no LANGSMITH_API_KEY)")
        return False

    # LangSmith + LangChain both read these; set explicitly (not setdefault).
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

    log.info(
        "LangSmith tracing ON — project '%s' at %s",
        settings.langsmith_project,
        settings.langsmith_endpoint,
    )
    return True
