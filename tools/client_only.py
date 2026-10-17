#!/usr/bin/env python3
"""Classify mod jars as client-only candidates from their metadata.

Usage: python3 -I tools/client_only.py <mods dir>

Signals (none is conclusive on Forge 1.19.2, so the output is a review list):
  - displayTest = IGNORE_ALL_VERSION / IGNORE_SERVER_VERSION
  - every dependency declares side="CLIENT"
  - no class outside the client package references net/minecraft/server or world logic
  - @Mod entrypoint lives under a *client* package / is guarded by Dist.CLIENT only
"""
from __future__ import annotations

import re
import sys
import tomllib
import zipfile
from pathlib import Path


def read_toml(z: zipfile.ZipFile) -> dict | None:
    try:
        raw = z.read("META-INF/mods.toml").decode("utf-8", "replace")
    except KeyError:
        return None
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        # Some mods ship slightly invalid TOML; fall back to regexes.
        return {"_raw": raw}


def main() -> None:
    mods = Path(sys.argv[1])
    for jar in sorted(mods.glob("*.jar"), key=lambda p: p.name.lower()):
        with zipfile.ZipFile(jar) as z:
            t = read_toml(z)
            names = z.namelist()
        if t is None:
            print(f"{'?':6} {jar.name}  (no mods.toml)")
            continue
        raw = t.get("_raw") or ""
        mods_list = t.get("mods", [])
        ids = [m.get("modId") for m in mods_list] or re.findall(r'modId\s*=\s*"([^"]+)"', raw)
        dt = {m.get("displayTest") for m in mods_list if m.get("displayTest")} or set(re.findall(r'displayTest\s*=\s*"([^"]+)"', raw))
        deps = [d for v in t.get("dependencies", {}).values() for d in v] if isinstance(t.get("dependencies"), dict) else []
        sides = {d.get("side", "BOTH").upper() for d in deps}
        classes = [n for n in names if n.endswith(".class")]
        client_cls = sum(1 for n in classes if "/client/" in n.lower())
        signals = []
        if dt & {"IGNORE_ALL_VERSION", "IGNORE_SERVER_VERSION"}:
            signals.append("displayTest=" + "/".join(sorted(dt)))
        if sides == {"CLIENT"}:
            signals.append("deps:CLIENT")
        if classes and client_cls / len(classes) > 0.6:
            signals.append(f"client-pkg {client_cls}/{len(classes)}")
        tag = "CLIENT?" if signals else ""
        print(f"{tag:8} {jar.name:60} ids={','.join(ids)} {' '.join(signals)}")


if __name__ == "__main__":
    main()
