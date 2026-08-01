#!/usr/bin/env python3
"""Test configured API keys without printing secret values."""

import os
import sys
from pathlib import Path

# Load .env manually (no dotenv dependency required)
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

import httpx

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP (not configured)"


def mask(key: str | None) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def result(name: str, status: str, detail: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail}


def test_openai() -> dict:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return result("OpenAI", SKIP)
    try:
        r = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
        if r.status_code == 200:
            return result("OpenAI", PASS, f"models endpoint OK ({len(r.json().get('data', []))} models visible)")
        return result("OpenAI", FAIL, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        return result("OpenAI", FAIL, str(e))


def test_langsmith() -> dict:
    key = os.environ.get("LANGSMITH_API_KEY", "")
    project = os.environ.get("LANGSMITH_PROJECT", "default")
    if not key:
        return result("LangSmith", SKIP)
    try:
        r = httpx.get(
            "https://api.smith.langchain.com/info",
            headers={"x-api-key": key},
            timeout=20,
        )
        if r.status_code == 200:
            return result("LangSmith", PASS, f"API reachable; project configured as '{project}'")
        return result("LangSmith", FAIL, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        return result("LangSmith", FAIL, str(e))


def test_newsapi() -> dict:
    key = os.environ.get("NEWSAPI_KEY", "")
    if not key:
        return result("NewsAPI", SKIP)
    try:
        r = httpx.get(
            "https://newsapi.org/v2/top-headlines",
            params={"country": "us", "pageSize": 1, "apiKey": key},
            timeout=20,
        )
        data = r.json()
        if r.status_code == 200 and data.get("status") == "ok":
            return result("NewsAPI", PASS, "top-headlines OK")
        return result("NewsAPI", FAIL, data.get("message") or f"HTTP {r.status_code}")
    except Exception as e:
        return result("NewsAPI", FAIL, str(e))


def test_fmp() -> dict:
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        return result("FMP (Financial Modeling Prep)", SKIP)
    try:
        r = httpx.get(
            "https://financialmodelingprep.com/stable/profile",
            params={"symbol": "AAPL", "apikey": key},
            timeout=20,
        )
        data = r.json()
        if r.status_code == 200 and isinstance(data, list) and data:
            return result("FMP (Financial Modeling Prep)", PASS, "AAPL profile OK (stable API)")
        if isinstance(data, dict) and data.get("Error Message"):
            return result("FMP (Financial Modeling Prep)", FAIL, data["Error Message"][:120])
        return result("FMP (Financial Modeling Prep)", FAIL, f"HTTP {r.status_code}: {str(data)[:120]}")
    except Exception as e:
        return result("FMP (Financial Modeling Prep)", FAIL, str(e))


def test_tavily() -> dict:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return result("Tavily", SKIP)
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": "NVDA stock", "max_results": 1},
            timeout=20,
        )
        if r.status_code == 200 and "results" in r.json():
            return result("Tavily", PASS, "search OK")
        return result("Tavily", FAIL, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        return result("Tavily", FAIL, str(e))


def test_polygon() -> dict:
    key = os.environ.get("POLYGON_API_KEY", "")
    if not key:
        return result("Massive (formerly Polygon)", SKIP)
    for base, label in [("https://api.massive.com", "api.massive.com"), ("https://api.polygon.io", "api.polygon.io")]:
        try:
            r = httpx.get(
                f"{base}/v2/aggs/ticker/AAPL/prev",
                params={"apiKey": key},
                timeout=20,
            )
            if r.status_code == 200 and r.json().get("results"):
                return result("Massive (formerly Polygon)", PASS, f"AAPL quote OK via {label}")
            return result("Massive (formerly Polygon)", FAIL, f"{label}: HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:  # noqa: BLE001
            continue
    return result("Massive (formerly Polygon)", FAIL, "both api.massive.com and api.polygon.io failed")


def test_alpha_vantage() -> dict:
    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not key:
        return result("Alpha Vantage", SKIP)
    try:
        r = httpx.get(
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": "IBM", "apikey": key},
            timeout=20,
        )
        data = r.json()
        if "Global Quote" in data and data["Global Quote"]:
            return result("Alpha Vantage", PASS, "GLOBAL_QUOTE OK")
        if "Note" in data:
            return result("Alpha Vantage", FAIL, data["Note"])
        if "Information" in data:
            return result("Alpha Vantage", FAIL, data["Information"])
        return result("Alpha Vantage", FAIL, str(data)[:120])
    except Exception as e:
        return result("Alpha Vantage", FAIL, str(e))


def test_fred() -> dict:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        return result("FRED", SKIP)
    try:
        r = httpx.get(
            "https://api.stlouisfed.org/fred/series",
            params={"series_id": "GDP", "api_key": key, "file_type": "json"},
            timeout=20,
        )
        if r.status_code == 200 and "seriess" in r.json():
            return result("FRED", PASS, "GDP series OK")
        return result("FRED", FAIL, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        return result("FRED", FAIL, str(e))


def test_google() -> dict:
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        return result("Google Gemini", SKIP)
    try:
        r = httpx.get(
            f"https://generativelanguage.googleapis.com/v1/models?key={key}",
            timeout=20,
        )
        if r.status_code == 200:
            return result("Google Gemini", PASS, "models list OK")
        return result("Google Gemini", FAIL, f"HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        return result("Google Gemini", FAIL, str(e))


def test_yfinance() -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker("AAPL").info
        if info and info.get("symbol"):
            return result("yfinance (no key)", PASS, f"AAPL profile: {info.get('shortName', 'OK')}")
        return result("yfinance (no key)", FAIL, "empty response")
    except Exception as e:
        return result("yfinance (no key)", FAIL, str(e))


def test_sec_edgar() -> dict:
    ua = os.environ.get(
        "SEC_USER_AGENT",
        "AI Investment Research Platform test@example.com",
    )
    try:
        r = httpx.get(
            "https://data.sec.gov/submissions/CIK0000320193.json",
            headers={"User-Agent": ua, "Accept": "application/json"},
            timeout=20,
        )
        if r.status_code == 200 and r.json().get("cik"):
            return result("SEC EDGAR (no key)", PASS, "Apple CIK lookup OK")
        return result("SEC EDGAR (no key)", FAIL, f"HTTP {r.status_code}")
    except Exception as e:
        return result("SEC EDGAR (no key)", FAIL, str(e))


def main():
    tests = [
        test_openai,
        test_langsmith,
        test_newsapi,
        test_fmp,
        test_tavily,
        test_polygon,
        test_alpha_vantage,
        test_fred,
        test_google,
        test_yfinance,
        test_sec_edgar,
    ]

    print("API Key Health Check")
    print("=" * 60)
    passed = failed = skipped = 0
    for fn in tests:
        r = fn()
        icon = {"PASS": "+", "FAIL": "X", SKIP: "-"}.get(r["status"], "?")
        print(f"[{icon}] {r['name']}: {r['status']}")
        if r["detail"]:
            print(f"    {r['detail']}")
        if r["status"] == PASS:
            passed += 1
        elif r["status"] == FAIL:
            failed += 1
        else:
            skipped += 1

    print("=" * 60)
    print(f"Passed: {passed}  Failed: {failed}  Skipped: {skipped}")

    # Keys present in .env (masked)
    print("\nConfigured keys (masked):")
    for var in [
        "OPENAI_API_KEY", "LANGSMITH_API_KEY", "NEWSAPI_KEY", "FMP_API_KEY",
        "TAVILY_API_KEY", "POLYGON_API_KEY", "ALPHA_VANTAGE_API_KEY",
        "FRED_API_KEY", "GOOGLE_API_KEY",
    ]:
        val = os.environ.get(var, "")
        print(f"  {var}: {mask(val) if val else '(not set)'}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
