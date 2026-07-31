"""
config.py

Configuration for the Collaborative Investment Research Platform.
Loads environment variables, provides the LLM factory (OpenAI or Google,
selectable via LLM_PROVIDER), and defines rate-limit constants and
data-quality thresholds shared across agents and tools.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- LLM Configuration ---
# Both providers are supported; LLM_PROVIDER picks which one get_llm() returns.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # "openai" or "google"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")


def get_llm(temperature: float = 0.0):
    """Factory function to create the appropriate LLM based on LLM_PROVIDER."""
    if LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=GOOGLE_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=temperature,
        )

    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=temperature,
    )


# --- Financial Data APIs ---
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
# yfinance is PRIMARY for financial data (no official rate limit). Alpha Vantage
# is FALLBACK only — its free tier is too tight to rely on primarily.
ALPHA_VANTAGE_RATE_LIMIT_PER_MINUTE = 5
ALPHA_VANTAGE_RATE_LIMIT_PER_DAY = 25

# --- News APIs ---
# NewsAPI.org is PRIMARY; Alpha Vantage NEWS_SENTIMENT (shares the key above)
# is FALLBACK if NewsAPI fails or is unavailable.
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

# --- Macro Data (FRED) ---
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# --- Data-quality thresholds ---
# Sentiment Analyst: fewer than this many articles in the lookback window
# means the agent must flag low-coverage rather than overstate confidence.
LOW_NEWS_COVERAGE_THRESHOLD = 3
SENTIMENT_LOOKBACK_DAYS = 30

# Financial Analyst: companies with less trading/filing history than this
# (recent IPOs, foreign issuers) get flagged as incomplete/stale instead of
# having ratios computed off partial data.
MIN_FINANCIAL_HISTORY_DAYS = 365

# Macro & Industry Analyst: trend window for FRED indicators and sector ETF
# performance windows (brief specifies 6-12mo indicator trend, 3mo/6mo/YTD ETF).
MACRO_TREND_LOOKBACK_MONTHS = 12
SECTOR_PERFORMANCE_WINDOWS = ["3mo", "6mo", "ytd"]

# --- LangSmith (tracing, used for inspecting Orchestrator reasoning_chain) ---
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "investment-research-platform")

if LANGSMITH_API_KEY:
    # LangChain's tracing SDK reads the LANGCHAIN_* names (LANGSMITH_* are
    # just where we ask the user for them in .env); propagate them so
    # tracing actually activates instead of silently doing nothing.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", LANGSMITH_API_KEY)
    os.environ.setdefault("LANGCHAIN_PROJECT", LANGSMITH_PROJECT)

# --- Checkpointer ---
CHECKPOINT_DB = os.getenv("CHECKPOINT_DB", "checkpoints.db")

# --- Committee approval (Checkpoint #2) ---
# Caps the revise -> re-review cycle so a stuck committee/feedback loop
# can't run forever; past this, the session is force-closed as rejected.
MAX_REVISION_ROUNDS = 3
