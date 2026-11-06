#!/usr/bin/env python3
"""Training-metric monitor: appends observation-only flags to eval/MONITOR.log.

Deep-trunk runs are touchier than shallow ones; flags are advisory. This script
NEVER intervenes in training. Requires deploy/env.sh-style env vars: WORKSPACE,
RUN_DIR, VENV_PY. Wire into the watchdog loop every 15 min:
  monitor.py || true
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ["WORKSPACE"])
RUN_DIR = Path(os.environ["RUN_DIR"])
METRICS = RUN_DIR / "training_metrics.jsonl"
OUT = WORKSPACE / "eval" / "MONITOR.log"

FLAGS = {
    "entropy_low": lambda d, h: d.get("entropy", 1) < 0.3,
    "entropy_collapse": lambda d, h: d.get("entropy", 1) < 0.15,
    "ev_low": lambda d, h: d.get("explained_variance", d.get("ev", 1)) < 0.7,
    "ev_critical": lambda d, h: d.get("explained_variance", d.get("ev", 1)) < 0.5,
    "side_us_low": lambda d, h: d.get("us_win_rate", 0.5) < 0.40,
    "side_us_high": lambda d, h: d.get("us_win_rate", 0.5) > 0.60,
    "kl_high": lambda d, h: d.get("kl", 0) > 0.08,
    "throughput_low": lambda d, h: d.get("steps_per_sec_avg", 1e9) < 15000,
}


def tail_rows(path, n=20):
    rows = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 256 * 1024))
            lines = [l for l in f.read().splitlines() if l.strip()]
        for l in lines[-n:]:
            rows.append(json.loads(l))
    except Exception:
        pass
    return rows


def main():
    rows = tail_rows(METRICS)
    if not rows:
        print("no metrics yet", file=sys.stderr)
        return
    d = rows[-1]
    hist = rows
    flags = [k for k, fn in FLAGS.items() if fn(d, hist)]
    line = (
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"steps={d.get('total_steps', 0)} stps={d.get('steps_per_sec_avg', 0)} "
        f"ent={d.get('entropy', -1):.3f} ev={d.get('explained_variance', d.get('ev', -1)):.3f} "
        f"us_win={d.get('us_win_rate', -1):.3f} kl={d.get('kl', -1):.4f} "
        f"flags={'|'.join(flags) if flags else '-'}"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        f.write(line + "\n")
    if "ev_critical" in flags or "entropy_collapse" in flags:
        print("URGENT: " + line, file=sys.stderr)


if __name__ == "__main__":
    main()
