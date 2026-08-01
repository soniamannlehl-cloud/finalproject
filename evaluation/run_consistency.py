#!/usr/bin/env python3
"""
LangSmith evaluation harness — recommendation consistency across repeated runs.

Usage:
    python evaluation/run_consistency.py --ticker NVDA --runs 3

Requires LANGSMITH_API_KEY and OPENAI_API_KEY. The API service must be running.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

API_BASE = "http://localhost:8080"


async def start_and_confirm(ticker: str) -> str:
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(f"{API_BASE}/runs", json={"query": ticker})
        resp.raise_for_status()
        data = resp.json()
        run_id = data["run_id"]

        if data.get("awaiting_human"):
            resp = await client.post(
                f"{API_BASE}/runs/{run_id}/resume",
                json={"action": "confirm"},
            )
            resp.raise_for_status()

        return run_id


async def wait_for_checkpoint(client: httpx.AsyncClient, run_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = await client.get(f"{API_BASE}/runs/{run_id}")
        resp.raise_for_status()
        data = resp.json()
        if data.get("awaiting_human"):
            return data
        if data.get("status") in ("complete", "approved", "rejected", "error"):
            return data
        await asyncio.sleep(5)
    raise TimeoutError(f"run {run_id} did not reach checkpoint in {timeout_s}s")


async def run_single(ticker: str, auto_approve: bool) -> dict:
    async with httpx.AsyncClient(timeout=300.0) as client:
        run_id = await start_and_confirm(ticker)

        data = await wait_for_checkpoint(client, run_id)
        if data.get("checkpoint", {}).get("type") == "checkpoint_2_committee_review" and auto_approve:
            resp = await client.post(
                f"{API_BASE}/runs/{run_id}/resume",
                json={"action": "approve"},
            )
            resp.raise_for_status()
            await asyncio.sleep(3)

        rec_resp = await client.get(f"{API_BASE}/runs/{run_id}/recommendation")
        rec = rec_resp.json().get("recommendation") or {}

        return {
            "run_id": run_id,
            "action": rec.get("action"),
            "confidence": rec.get("confidence"),
            "evidence_score": rec.get("evidence_score"),
        }


def analyze_results(results: list[dict]) -> dict:
    actions = [r.get("action") for r in results if r.get("action")]
    unique_actions = set(actions)
    confidences = [r.get("confidence") for r in results if r.get("confidence") is not None]

    return {
        "run_count": len(results),
        "actions": actions,
        "unique_actions": sorted(unique_actions),
        "action_consistent": len(unique_actions) <= 1,
        "confidence_range": [min(confidences), max(confidences)] if confidences else None,
        "results": results,
    }


async def main():
    parser = argparse.ArgumentParser(description="Evaluate recommendation consistency")
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--no-approve", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("evaluation/results.json"))
    args = parser.parse_args()

    print(f"Running {args.runs} evaluation run(s) for {args.ticker}…")
    results = []
    for i in range(args.runs):
        print(f"  Run {i + 1}/{args.runs}…")
        try:
            result = await run_single(args.ticker, auto_approve=not args.no_approve)
            results.append(result)
            print(f"    → {result.get('action')} (confidence {result.get('confidence')})")
        except Exception as e:  # noqa: BLE001
            print(f"    → FAILED: {e}", file=sys.stderr)
            results.append({"error": str(e)})

    summary = analyze_results([r for r in results if "error" not in r])
    summary["errors"] = [r for r in results if "error" in r]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2))
    print(f"\nResults written to {args.output}")
    print(f"Action consistent: {summary.get('action_consistent')}")
    print(f"Actions seen: {summary.get('unique_actions')}")


if __name__ == "__main__":
    asyncio.run(main())
