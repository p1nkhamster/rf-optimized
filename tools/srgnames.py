#!/usr/bin/env python3
"""Look up SRG names for Mojang-named members (for testkit/mod, which compiles against the SRG jar).

Usage: python3 -I tools/srgnames.py net.minecraft.client.Minecraft.getInstance [Class.member ...]
Obfuscated names collide across members, so several candidates may print; pick by signature.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

LIBS = Path.home() / ".local/share/PrismLauncher/libraries"
MC = "1.19.2-20220805.130853"


def main() -> None:
    want: dict[str, set[str]] = {}
    for a in sys.argv[1:]:
        c, m = a.rsplit(".", 1)
        want.setdefault(c, set()).add(m)
    obf: dict[str, tuple[str, dict]] = {}
    cur = None
    for line in (LIBS / f"net/minecraft/client/{MC}/client-{MC}-mappings.txt").read_text().splitlines():
        if not line.startswith(" ") and line.endswith(":"):
            name, o = line[:-1].split(" -> ")
            cur = name if name in want else None
            if cur:
                obf[cur] = (o, {})
        elif cur and not line.startswith("#"):
            m = re.match(r"\s+(?:\d+:\d+:)?(\S+) ([\w$<>]+)(\([^)]*\))? -> (\S+)", line)
            if m and m.group(2) in want[cur]:
                obf[cur][1].setdefault(m.group(2), []).append((m.group(4), m.group(3) or "", m.group(1)))
    srg: dict[str, dict[str, list[str]]] = {}
    cls = None
    tsrg = LIBS / f"de/oceanlabs/mcp/mcp_config/{MC}/mcp_config-{MC}-mappings-merged.txt"
    for line in tsrg.read_text().splitlines():
        if not line.startswith("\t"):
            p = line.split()
            cls = p[0] if len(p) >= 2 else None
        elif cls and not line.startswith("\t\t"):
            p = line.strip().split()
            # method lines: obf desc srg [id]; field lines: obf srg
            srg.setdefault(cls, {}).setdefault(p[0], []).append(p[2] if len(p) >= 3 and p[1].startswith("(") else p[1])
    for c, (o, members) in obf.items():
        for name, entries in members.items():
            for ob, sig, ret in entries:
                cands = sorted(set(srg.get(o.replace(".", "/"), {}).get(ob, [])))
                kind = "m_" if sig else "f_"
                print(f"{c}.{name}{sig} : {ret} -> {[x for x in cands if x.startswith(kind)] or cands}")


if __name__ == "__main__":
    main()
