#!/usr/bin/env python3
"""Print a markdown summary from evaluation/results.json."""

import json
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "evaluation/results.json")
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(path.read_text())
    print("# Evaluation Summary\n")
    print(f"- **Runs completed:** {data.get('run_count', 0)}")
    print(f"- **Actions observed:** {', '.join(data.get('actions', [])) or 'none'}")
    print(f"- **Action consistent:** {data.get('action_consistent', 'n/a')}")
    if data.get("confidence_range"):
        lo, hi = data["confidence_range"]
        print(f"- **Confidence range:** {lo:.2f} – {hi:.2f}")
    if data.get("errors"):
        print(f"- **Errors:** {len(data['errors'])}")
    print("\n## Per-run results\n")
    for r in data.get("results", []):
        print(f"- `{r.get('run_id', '?')}`: **{r.get('action')}** (confidence {r.get('confidence')})")


if __name__ == "__main__":
    main()
