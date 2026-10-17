#!/usr/bin/env python3
"""Find oversized textures in jars, resource-pack zips and loose resource folders.

Usage: python3 -I tools/scan_textures.py <path> [<path> ...]   (files or directories; directories are walked)

Reports, per source:
  - atlas textures (textures/block, textures/item, textures/particle...) whose frame width is above 16 px
    — these are stitched into the shared atlases, so their cost is width² per frame (+ mip levels)
  - any texture larger than 1024 px on a side (title panoramas, big GUI art, entity sheets)
"""
from __future__ import annotations

import os
import struct
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ATLAS_DIRS = ("/textures/block/", "/textures/item/", "/textures/particle/", "/textures/mob_effect/", "/textures/painting/")


def png_size(head: bytes) -> tuple[int, int] | None:
    if head[:8] != b"\x89PNG\r\n\x1a\n" or len(head) < 24:
        return None
    return struct.unpack(">II", head[16:24])


def iter_pngs(src: Path):
    """Yield (relpath, width, height) for each PNG in a jar/zip or a directory tree."""
    if src.is_dir():
        for dp, _dns, fns in os.walk(src):
            for n in fns:
                if n.endswith(".png"):
                    p = Path(dp) / n
                    with open(p, "rb") as fh:
                        sz = png_size(fh.read(24))
                    if sz:
                        yield p.relative_to(src).as_posix(), *sz
    else:
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                if info.filename.endswith(".png"):
                    with z.open(info) as fh:
                        sz = png_size(fh.read(24))
                    if sz:
                        yield info.filename, *sz


def scan(src: Path) -> dict:
    out = {"atlas_big": [], "huge": [], "atlas_px": 0, "atlas_px_at16": 0}
    for rel, w, h in iter_pngs(src):
        r = "/" + rel
        if any(d in r for d in ATLAS_DIRS):
            frames = max(1, h // w) if h >= w else 1
            px = w * w * frames if h >= w else w * h
            out["atlas_px"] += px
            out["atlas_px_at16"] += min(px, 16 * 16 * frames) if w > 16 else px
            if w > 16:
                out["atlas_big"].append((rel, w, h))
        if max(w, h) > 1024:
            out["huge"].append((rel, w, h))
    return out


def main() -> None:
    targets: list[Path] = []
    for a in sys.argv[1:]:
        p = Path(a)
        if p.is_file():
            targets.append(p)
        else:
            targets += sorted(x for x in p.iterdir() if x.suffix in (".jar", ".zip") or x.is_dir())
    rows = []
    for t in targets:
        try:
            r = scan(t.resolve())
        except zipfile.BadZipFile:
            continue
        if r["atlas_big"] or r["huge"]:
            rows.append((r["atlas_px"] - r["atlas_px_at16"], t, r))
    rows.sort(key=lambda x: -x[0])
    total = 0
    for saving, t, r in rows:
        total += saving
        widths = defaultdict(int)
        for _, w, _ in r["atlas_big"]:
            widths[w] += 1
        print(f"{t.name[:60]:60} oversized-atlas={len(r['atlas_big']):4} by-width={dict(sorted(widths.items()))} "
              f"atlas-px-saving={saving / 1e6:.2f}Mpx huge={len(r['huge'])}")
        for rel, w, h in r["huge"][:6]:
            print(f"      huge: {rel} {w}x{h}")
    print(f"\nTotal atlas pixels saved by capping at 16x: {total / 1e6:.2f} Mpx (~{total * 4 / 2**20:.0f} MiB RGBA before mips)")


if __name__ == "__main__":
    main()
