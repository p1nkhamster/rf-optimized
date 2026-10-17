"""Per-mod patches: key-level config edits and file rewrites inside jars / resource packs.

changes.toml drives everything:

    [[config]]                       # edit one config file in the staged .minecraft tree
    file = "config/ferritecore-mixin.toml"
    set = { compactFastMap = "true" }        # TOML: "section.key" for keys under [section]; raw TOML values
    reason = "..."

    [[config]]
    file = "config/embeddium-options.json"
    set = { "performance.chunk_builder_threads" = 2 }   # JSON: dotted path, JSON values

    [[config]]
    file = "config/modernfix-mixins.properties"
    set = { "mixin.perf.dynamic_resources" = "true" }   # properties / txt "key: value" files

    [[config]]                       # exact text replacement, for formats without a parser (json5, cfg)
    file = "config/prettyrain.json5"
    replace = [['"maxParticleAmount": 1500', '"maxParticleAmount": 600']]

    [[jar_patch]]                    # rewrite files inside one jar/zip (it then ships in overrides/)
    file = "Pretty Rain-1.19.2-Forge-1.1.1.jar"
    resize = { "assets/particlerain/textures/particle/fog_dithered.png" = 256 }
    reason = "..."
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

PATCH_VERSION = 1  # bump to invalidate cached patched jars


# --------------------------------------------------------------------------- config files

def _set_toml(text: str, key: str, value: str) -> str:
    section, _, name = key.rpartition(".")
    lines = text.splitlines()
    in_section = section == ""
    header = re.compile(r"^\s*\[+\s*([^\]]+?)\s*\]+\s*$")
    for i, line in enumerate(lines):
        m = header.match(line)
        if m:
            in_section = m.group(1) == section
            continue
        if in_section and re.match(rf"^\s*{re.escape(name)}\s*=", line):
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = f"{indent}{name} = {value}"
            return "\n".join(lines) + "\n"
    if section == "":
        # Top-level key not present: prepend so it stays outside any table.
        return f"{name} = {value}\n" + text
    raise KeyError(f"{key} not found")


def _set_json(text: str, key: str, value) -> str:
    data = json.loads(text)
    node = data
    *path, last = key.split(".")
    for p in path:
        node = node[p]
    if last not in node:
        raise KeyError(f"{key} not found")
    node[last] = value
    return json.dumps(data, indent=2) + "\n"


def _set_props(text: str, key: str, value: str, sep: str) -> str:
    pat = re.compile(rf"^{re.escape(key)}\s*{re.escape(sep.strip())}.*$", re.M)
    line = f"{key}{sep}{value}"
    if pat.search(text):
        return pat.sub(lambda _m: line, text)
    return text.rstrip("\n") + "\n" + line + "\n"


def edit_config(path: Path, changes: dict) -> None:
    text = path.read_text() if path.exists() else ""
    for key, value in changes.items():
        if path.suffix in (".toml", ".ini"):
            text = _set_toml(text, key, value if isinstance(value, str) else json.dumps(value))
        elif path.suffix == ".json":
            text = _set_json(text, key, value)
        elif path.suffix == ".properties":
            text = _set_props(text, key, str(value).lower() if isinstance(value, bool) else str(value), "=")
        elif path.suffix == ".txt":
            text = _set_props(text, key, str(value).lower() if isinstance(value, bool) else str(value), ": ")
        else:
            raise ValueError(f"don't know how to edit {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def apply_tree(cfg: dict, st: Path) -> None:
    """Apply [[config]] edits to the staged .minecraft tree."""
    for c in cfg.get("config", []):
        target = st / c["file"]
        if not target.exists() and not c.get("create", False):
            raise SystemExit(f"[[config]] {c['file']}: file not in pack (set create = true to create it)")
        try:
            if "set" in c:
                edit_config(target, c["set"])
            for old, new in c.get("replace", []):
                # Plain text replacement for formats without a parser here (json5, cfg); must match exactly once.
                text = target.read_text()
                if text.count(old) != 1:
                    raise KeyError(f"replace: {old!r} found {text.count(old)} times")
                target.write_text(text.replace(old, new))
        except KeyError as e:
            raise SystemExit(f"[[config]] {c['file']}: {e}") from None


# --------------------------------------------------------------------------- jar / zip patches

def _resize_png(data: bytes, max_px: int) -> bytes:
    p = subprocess.run(["magick", "png:-", "-filter", "Box", "-resize", f"{max_px}x{max_px}>", "-strip", "png:-"],
                       input=data, capture_output=True, check=True)
    return p.stdout


def _patch_zip(src: Path, dst: Path, rule: dict) -> None:
    resize: dict = rule.get("resize", {})
    drop = set(rule.get("drop", []))
    seen = set()
    tmp = dst.with_name(dst.name + ".tmp")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename in drop:
                seen.add(info.filename)
                continue
            data = zin.read(info)
            if info.filename in resize:
                data = _resize_png(data, int(resize[info.filename]))
                seen.add(info.filename)
            zout.writestr(info, data)
    missing = (set(resize) | drop) - seen
    if missing:
        tmp.unlink()
        raise SystemExit(f"[[jar_patch]] {src.name}: entries not found: {sorted(missing)}")
    tmp.replace(dst)


def apply(cfg: dict, entries: list, cache: Path) -> None:
    """Apply [[jar_patch]] rules; patched entries point at a cached rewritten copy."""
    by_name = {e.filename: e for e in entries}
    for rule in cfg.get("jar_patch", []):
        e = by_name.get(rule["file"])
        if e is None:
            raise SystemExit(f"[[jar_patch]] {rule['file']}: not in pack")
        key = hashlib.sha256(json.dumps([PATCH_VERSION, e.filename, e.path.stat().st_size,
                                         rule.get("resize"), rule.get("drop")], sort_keys=True).encode()).hexdigest()[:16]
        dst = cache / key / e.filename
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            _patch_zip(e.path, dst, rule)
        e.path, e.patched = dst, True
        e.reason = e.reason or rule["reason"]
