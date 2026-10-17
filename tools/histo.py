#!/usr/bin/env python3
"""Summarise / diff jcmd GC.class_histogram dumps.

Usage:
    python3 -I tools/histo.py results/baseline-travel2.histo                 # top classes + top packages
    python3 -I tools/histo.py results/baseline-travel2.histo results/opt-travel2.histo   # diff (b - a)

Packages are cut to 3 segments (e.g. com.simibubi.create) so the owner mod is visible. Arrays/primitives
and JDK classes are kept as their own buckets since they can't be attributed to a mod from a histogram.
"""
from __future__ import annotations

import re
import sys
from collections import Counter

ROW = re.compile(r"^\s*\d+:\s+(\d+)\s+(\d+)\s+(\S+)")


def load(path: str) -> tuple[Counter, Counter, Counter]:
    by_class, count, by_pkg = Counter(), Counter(), Counter()
    for line in open(path, errors="replace"):
        m = ROW.match(line)
        if not m:
            continue
        n, size, cls = int(m.group(1)), int(m.group(2)), m.group(3)
        by_class[cls] += size
        count[cls] += n
        if cls.startswith("["):
            pkg = "(arrays) " + cls
        else:
            parts = cls.split(".")
            pkg = ".".join(parts[: 3 if len(parts) > 3 else max(1, len(parts) - 1)])
        by_pkg[pkg] += size
    return by_class, count, by_pkg


def mb(x: float) -> str:
    return f"{x / 2**20:8.1f}MB"


def main() -> None:
    if len(sys.argv) == 2:
        cls, cnt, pkg = load(sys.argv[1])
        print(f"total {mb(sum(cls.values()))}\n\n-- top packages")
        for k, v in pkg.most_common(40):
            print(f"{mb(v)}  {k}")
        print("\n-- top classes")
        for k, v in cls.most_common(30):
            print(f"{mb(v)}  {cnt[k]:>10}  {k}")
    else:
        a_cls, a_cnt, a_pkg = load(sys.argv[1])
        b_cls, b_cnt, b_pkg = load(sys.argv[2])
        print(f"total {mb(sum(a_cls.values()))} -> {mb(sum(b_cls.values()))}\n\n-- package deltas")
        d = Counter({k: b_pkg[k] - a_pkg[k] for k in set(a_pkg) | set(b_pkg)})
        for k, v in sorted(d.items(), key=lambda kv: kv[1])[:30]:
            print(f"{mb(v)}  {mb(a_pkg[k])} -> {mb(b_pkg[k])}  {k}")
        print("\n-- class deltas")
        d = Counter({k: b_cls[k] - a_cls[k] for k in set(a_cls) | set(b_cls)})
        for k, v in sorted(d.items(), key=lambda kv: kv[1])[:25]:
            print(f"{mb(v)}  {a_cnt[k]:>9} -> {b_cnt[k]:>9}  {k}")


if __name__ == "__main__":
    main()
