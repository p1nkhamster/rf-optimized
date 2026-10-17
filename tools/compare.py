#!/usr/bin/env python3
"""Side-by-side table of measure.py results.  Usage: python3 -I tools/compare.py baseline opt1 [opt2 ...]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "results"


def row(name: str, vals: list) -> str:
    return f"{name:28}" + "".join(f"{'-' if v is None else v:>12}" for v in vals)


def main() -> None:
    runs = [json.loads((RES / f"{l}.json").read_text()) for l in sys.argv[1:]]
    print(row("", sys.argv[1:]))
    print(row("time to title (s)", [r.get("title_after_s") for r in runs]))
    print(row("time to world (s)", [r.get("joined_after_s") for r in runs]))
    for m in ("menu", "spawn", "travel1", "travel2", "return"):
        print(row(f"{m}: live heap MB", [r.get(m, {}).get("heap_live_mb") for r in runs]))
        print(row(f"{m}: committed heap MB", [r.get(m, {}).get("heap_committed_mb") for r in runs]))
        print(row(f"{m}: process RSS MB", [r.get(m, {}).get("VmRSS") for r in runs]))
    print(row("peak RSS MB", [r.get("peak_rss_mb") for r in runs]))
    print(row("server MSPT (travel2)", [r.get("travel2", {}).get("mspt") for r in runs]))
    for k in ("pauses", "max_ms", "p99_ms", "full_gcs"):
        print(row(f"GC {k}", [r.get("gc", {}).get(k) for r in runs]))
    fps = [sorted(s["fps"] for s in r.get("samples", [])) for r in runs]
    print(row("FPS median", [f[len(f) // 2] if f else None for f in fps]))
    print(row("errors", [r.get("error") or "ok" for r in runs]))


if __name__ == "__main__":
    main()
