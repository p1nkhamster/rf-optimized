#!/usr/bin/env python3
"""Build "Raspberry Flavoured Optimized" from upstream Raspberry Flavoured + changes.toml.

Usage:
    python3 -I build.py fetch      # download upstream pack + every mod into .cache/
    python3 -I build.py build      # fetch (if needed) and produce dist/ outputs
    python3 -I build.py build --no-server   # skip the Forge server install step

Outputs (dist/):
    Raspberry Flavoured Optimized-<ver>.zip          CurseForge-format modpack
    Raspberry Flavoured Optimized-<ver>-prism.zip    Prism Launcher instance export
    instance/                                         same instance, unpacked
    server/                                           Forge server pack (client-only mods removed)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # -I drops the script dir; we only import our own package

from rfopt import patches  # noqa: E402

CONFIG = ROOT / "changes.toml"
CACHE = ROOT / ".cache"
DIST = ROOT / "dist"
CF_API = "https://www.curseforge.com/api/v1/mods"
UA = {"User-Agent": "Mozilla/5.0 (rf-optimized build)"}
# Fixed timestamp so rebuilt zips are byte-identical when inputs are unchanged.
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


# --------------------------------------------------------------------------- download

def http_get(url: str, dest: Path | None = None, tries: int = 4) -> bytes | None:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                if dest is None:
                    return r.read()
                tmp = dest.with_name(dest.name + ".part")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "wb") as fh:
                    shutil.copyfileobj(r, fh, 1 << 20)
                tmp.replace(dest)
                return None
        except Exception as e:  # noqa: BLE001 - retried, then re-raised
            last = e
    raise RuntimeError(f"GET {url} failed: {last}")


def cf_meta(pid: int, fid: int) -> dict:
    p = CACHE / "meta" / f"{fid}.json"
    if not p.exists():
        d = json.loads(http_get(f"{CF_API}/{pid}/files/{fid}"))["data"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, indent=1))
    return json.loads(p.read_text())


def cf_file(pid: int, fid: int) -> Path:
    m = cf_meta(pid, fid)
    dest = CACHE / "cf" / str(fid) / m["fileName"]
    if not (dest.exists() and dest.stat().st_size == m["fileLength"]):
        http_get(f"{CF_API}/{pid}/files/{fid}/download", dest)
        if dest.stat().st_size != m["fileLength"]:
            raise RuntimeError(f"size mismatch for {dest.name}")
    return dest


def cf_cdn_url(fid: int, filename: str) -> str:
    return f"https://mediafilez.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{urllib.parse.quote(filename)}"


def sha512(p: Path) -> str:
    h = hashlib.sha512()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mr_file(entry: dict) -> Path:
    dest = CACHE / "mr" / entry["filename"]
    if not (dest.exists() and sha512(dest) == entry["sha512"]):
        http_get(entry["url"], dest)
        if sha512(dest) != entry["sha512"]:
            raise RuntimeError(f"sha512 mismatch for {dest.name}")
    return dest


# --------------------------------------------------------------------------- model

@dataclass
class Entry:
    """One jar or resource-pack zip that ends up in the pack."""
    filename: str
    path: Path               # local cached file
    folder: str              # "mods" | "resourcepacks"
    name: str                # human name, for reports
    pid: int | None = None   # CurseForge project id, if CF-hosted
    fid: int | None = None
    client_only: bool = False
    patched: bool = False    # True once a patch rewrote the file (then it ships in overrides)
    reason: str = ""
    tags: set = field(default_factory=set)
    license: str = ""        # SPDX id for jars we may bundle (non-CurseForge sources)
    url: str = ""            # public download URL (server installer uses it)


def load_config() -> dict:
    with open(CONFIG, "rb") as fh:
        return tomllib.load(fh)


def fix_perms(root: Path) -> None:
    # Upstream zip has entries stored with mode 000.
    for dp, dns, fns in os.walk(root):
        for n in dns:
            os.chmod(os.path.join(dp, n), 0o755)
        for n in fns:
            os.chmod(os.path.join(dp, n), 0o644)


def fetch_upstream(cfg: dict) -> Path:
    up = cfg["upstream"]
    zpath = cf_file(up["project"], up["file"])
    out = CACHE / "upstream" / str(up["file"])
    if not (out / "manifest.json").exists():
        tmp = out.with_name(out.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            for info in z.infolist():
                target = (tmp / info.filename).resolve()
                if not str(target).startswith(str(tmp.resolve()) + os.sep):
                    raise RuntimeError(f"unsafe path in upstream zip: {info.filename}")
            z.extractall(tmp)
        os.chmod(tmp, 0o755)
        fix_perms(tmp)
        shutil.rmtree(out, ignore_errors=True)
        tmp.rename(out)
    return out


def resolve(cfg: dict, jobs: int = 12) -> tuple[Path, dict, list[Entry]]:
    up = fetch_upstream(cfg)
    manifest = json.loads((up / "manifest.json").read_text())
    remove = {r["project"]: r for r in cfg.get("remove", [])}
    known_pids = {f["projectID"] for f in manifest["files"]}
    for pid in remove:
        if pid not in known_pids:
            raise SystemExit(f"changes.toml removes project {pid}, which is not in the upstream manifest")
    client_only = set(cfg.get("server", {}).get("client_only", []))

    def one(f: dict) -> Entry | None:
        pid, fid = f["projectID"], f["fileID"]
        meta = cf_meta(pid, fid)
        if pid in remove:
            return Entry(meta["fileName"], Path(), "", remove[pid].get("name", meta["fileName"]), pid, fid,
                         reason=remove[pid]["reason"], tags={"removed"})
        path = cf_file(pid, fid)
        folder = "mods" if meta["fileName"].endswith(".jar") else "resourcepacks"
        return Entry(meta["fileName"], path, folder, meta["displayName"], pid, fid, client_only=pid in client_only,
                     url=cf_cdn_url(fid, meta["fileName"]))

    with cf.ThreadPoolExecutor(jobs) as ex:
        results = list(ex.map(one, manifest["files"]))

    entries = [e for e in results if "removed" not in e.tags]
    removed = [e for e in results if "removed" in e.tags]

    for a in cfg.get("add", []):
        tags = {"added", *(["server_only"] if a.get("side") == "server" else [])}
        if "cf_project" in a:
            # CurseForge-hosted: referenced from the manifest, so the jar is never redistributed by us.
            pid, fid = a["cf_project"], a["cf_file"]
            meta = cf_meta(pid, fid)
            entries.append(Entry(meta["fileName"], cf_file(pid, fid), a.get("folder", "mods"), a["slug"], pid, fid,
                                 client_only=a.get("side") == "client", reason=a["reason"], tags=tags,
                                 license=a.get("license", ""), url=cf_cdn_url(fid, meta["fileName"])))
            continue
        path = mr_file(a)
        entries.append(Entry(a["filename"], path, a.get("folder", "mods"), a["slug"],
                             client_only=a.get("side") == "client", reason=a["reason"], tags=tags,
                             license=a.get("license", ""), url=a["url"]))
    return up, manifest, entries + removed


# --------------------------------------------------------------------------- staging

def copytree_overlay(src: Path, dst: Path) -> None:
    for dp, _dns, fns in os.walk(src):
        rel = Path(dp).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for n in fns:
            shutil.copy2(Path(dp) / n, dst / rel / n)


def stage(cfg: dict, up: Path, entries: list[Entry]) -> Path:
    """Build the full client .minecraft tree in dist/stage/minecraft."""
    st = DIST / "stage" / "minecraft"
    shutil.rmtree(st.parent, ignore_errors=True)
    st.mkdir(parents=True)

    copytree_overlay(up / "overrides", st)
    for rel in cfg.get("delete", {}).get("paths", []):
        target = st / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            print(f"  note: delete path not present: {rel}")
    # Removed mods' override jars (upstream ships two mods directly in overrides/mods).
    for rel in cfg.get("delete", {}).get("override_mods", []):
        (st / "mods" / rel).unlink()
    copytree_overlay(ROOT / "overrides", st)

    for e in entries:
        if "removed" in e.tags or "server_only" in e.tags:
            continue
        dest = st / e.folder / e.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(e.path, dest)
    return st


# --------------------------------------------------------------------------- outputs

def zip_dir(zf: zipfile.ZipFile, src: Path, prefix: str, skip=lambda rel: False) -> None:
    for p in sorted(src.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(src).as_posix()
        if skip(rel):
            continue
        info = zipfile.ZipInfo(f"{prefix}{rel}", ZIP_DATE)
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        # Already-compressed formats are stored; everything else deflated.
        info.compress_type = zipfile.ZIP_STORED if p.suffix in {".jar", ".zip", ".ogg", ".png"} else zipfile.ZIP_DEFLATED
        with open(p, "rb") as fh:
            zf.writestr(info, fh.read())


def write_cf_zip(cfg: dict, manifest: dict, st: Path, entries: list[Entry], out: Path) -> None:
    pack = cfg["pack"]
    cf_refs = [e for e in entries
               if e.pid is not None and not e.patched and "removed" not in e.tags and "server_only" not in e.tags]
    ref_names = {(e.folder, e.filename) for e in cf_refs}
    allowed = set(pack.get("bundle_licenses", []))
    for e in entries:
        bundled = "removed" not in e.tags and "server_only" not in e.tags and (e.pid is None or e.patched)
        if bundled and e.license not in allowed:
            raise SystemExit(f"{e.filename}: license {e.license or '(unknown)'} does not allow bundling; "
                             "reference it from CurseForge instead")
    new_manifest = {
        "minecraft": manifest["minecraft"],
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": pack["name"],
        "version": pack["version"],
        "author": pack["author"],
        "files": [{"projectID": e.pid, "fileID": e.fid, "required": True} for e in sorted(cf_refs, key=lambda e: e.pid)],
        "overrides": "overrides",
    }

    def skip(rel: str) -> bool:
        parts = rel.split("/", 1)
        return len(parts) == 2 and (parts[0], parts[1]) in ref_names

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("manifest.json", ZIP_DATE)
        zf.writestr(info, json.dumps(new_manifest, indent=2), zipfile.ZIP_DEFLATED)
        zip_dir(zf, st, "overrides/", skip)


def merge_options(dst: Path, src: Path) -> None:
    """Key-wise merge of an options.txt fragment into dst."""
    opts: dict[str, str] = {}
    if dst.exists():
        for line in dst.read_text().splitlines():
            k, sep, v = line.partition(":")
            if sep:
                opts[k] = v
    for line in src.read_text().splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith("#"):
            opts[k] = v
    dst.write_text("".join(f"{k}:{v}\n" for k, v in opts.items()))


def mmc_pack_json(cfg: dict, manifest: dict) -> str:
    forge = manifest["minecraft"]["modLoaders"][0]["id"].removeprefix("forge-")
    return json.dumps({
        # LWJGL is pinned explicitly: if Prism can't refresh its metadata it otherwise launches without it.
        "components": [
            {"dependencyOnly": True, "uid": "org.lwjgl3", "version": cfg["pack"].get("lwjgl", "3.3.1")},
            {"important": True, "uid": "net.minecraft", "version": manifest["minecraft"]["version"]},
            {"uid": "net.minecraftforge", "version": forge},
        ],
        "formatVersion": 1,
    }, indent=4)


PRISM_LIBS = Path.home() / ".local/share/PrismLauncher/libraries"
PRISM_JDK = Path.home() / ".local/share/PrismLauncher/java/java-runtime-gamma/bin"


def build_testkit_mod(mc: str, forge: str) -> Path:
    """Compile testkit/mod (test-only harness mod) against the SRG client jar Prism already installed."""
    src = ROOT / "testkit" / "mod"
    out = CACHE / "testkit" / "rftestkit.jar"
    inputs = [p for p in src.rglob("*") if p.is_file()]
    if out.exists() and all(p.stat().st_mtime < out.stat().st_mtime for p in inputs):
        return out
    srg_jar = next(PRISM_LIBS.glob(f"net/minecraft/client/{mc}-*/client-{mc}-*-srg.jar"), None)
    if srg_jar is None:
        raise SystemExit("testkit: SRG client jar not found; launch any Forge instance for this version in Prism once")
    # Only the libraries this Forge version launches with; Prism's library dir holds every version ever used.
    patterns = [f"net/minecraftforge/forge/{mc}-{forge}/forge-{mc}-{forge}-universal.jar",
                f"net/minecraftforge/fmlloader/{mc}-{forge}/*.jar", f"net/minecraftforge/fmlcore/{mc}-{forge}/*.jar",
                f"net/minecraftforge/javafmllanguage/{mc}-{forge}/*.jar", "net/minecraftforge/eventbus/6.0.3/*.jar",
                "net/minecraftforge/forgespi/6.0.0/*.jar", "com/mojang/logging/1.0.0/*.jar",
                "org/slf4j/slf4j-api/1.8.0-beta4/*.jar", "com/mojang/datafixerupper/5.0.28/*.jar",
                "com/mojang/brigadier/1.0.18/*.jar", "com/google/guava/guava/31.0.1-jre/*.jar",
                "it/unimi/dsi/fastutil/8.5.6/*.jar", "com/mojang/authlib/3.11.49/*.jar"]
    cp = [srg_jar, *(p for pat in patterns for p in sorted(PRISM_LIBS.glob(pat)))]
    classes = CACHE / "testkit" / "classes"
    shutil.rmtree(classes, ignore_errors=True)
    subprocess.run([str(PRISM_JDK / "javac"), "--release", "17", "-nowarn", "-d", str(classes),
                    "-cp", os.pathsep.join(map(str, cp)), *map(str, (src / "src").rglob("*.java"))], check=True)
    copytree_overlay(src / "resources", classes)
    out.unlink(missing_ok=True)
    subprocess.run([str(PRISM_JDK / "jar"), "--create", "--file", str(out), "-C", str(classes), "."], check=True)
    return out


def write_prism(cfg: dict, manifest: dict, st: Path, out_dir: Path, out_zip: Path, test: bool) -> None:
    pack, jvm = cfg["pack"], cfg["jvm"]
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    shutil.copytree(st, out_dir / "minecraft")
    if test:
        kit = ROOT / "testkit"
        copytree_overlay(kit / "minecraft", out_dir / "minecraft")
        merge_options(out_dir / "minecraft" / "options.txt", kit / "options.txt")
        mc_ver = manifest["minecraft"]["version"]
        forge_ver = manifest["minecraft"]["modLoaders"][0]["id"].removeprefix("forge-")
        shutil.copy2(build_testkit_mod(mc_ver, forge_ver), out_dir / "minecraft" / "mods" / "rftestkit.jar")
    (out_dir / "mmc-pack.json").write_text(mmc_pack_json(cfg, manifest))
    icon = st / "icon.png"
    cfg_lines = {
        "InstanceType": "OneSix",
        "name": f"{pack['name']} {pack['version']}",
        "iconKey": "rf_optimized" if icon.exists() else "default",
        "OverrideMemory": "true",
        "MinMemAlloc": str(jvm["min_mb"]),
        "MaxMemAlloc": str(jvm["max_mb"]),
        "OverrideJavaArgs": "true",
        "JvmArgs": " ".join(jvm["client_args"] + (jvm.get("test_args", []) if test else [])),
        "OverrideJavaLocation": "false",
        "AutomaticJava": "true",
        "ManagedPack": "false",
        **({"QuitAfterGameStop": "true", "ShowConsole": "false"} if test else {}),
    }
    (out_dir / "instance.cfg").write_text("[General]\n" + "".join(f"{k}={v}\n" for k, v in cfg_lines.items()))
    if icon.exists():
        shutil.copy2(icon, out_dir / "rf_optimized.png")
    out_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zip_dir(zf, out_dir, "")


FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"


def write_server(cfg: dict, manifest: dict, st: Path, entries: list[Entry], out: Path, java: str, install: bool) -> None:
    srv, jvm = cfg["server"], cfg["jvm"]
    mc = manifest["minecraft"]["version"]
    forge = manifest["minecraft"]["modLoaders"][0]["id"].removeprefix("forge-")
    # Keep a previous Forge install (libraries/) to avoid re-running the installer.
    keep = {"libraries", "run.sh", "run.bat", "user_jvm_args.txt"} if install else set()
    if out.exists():
        for p in out.iterdir():
            if p.name in keep or p.name in {"world", "logs", "eula.txt", "server.properties"}:
                continue
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    out.mkdir(parents=True, exist_ok=True)

    for d in ("config", "defaultconfigs", "kubejs"):
        if (st / d).exists():
            shutil.rmtree(out / d, ignore_errors=True)
            shutil.copytree(st / d, out / d)
    # Client-only folders inside config are harmless on the server, but resource packs / UI data are not needed.
    for rel in srv.get("strip_paths", []):
        p = out / rel
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)

    (out / "mods").mkdir(exist_ok=True)
    override_mods = {p.name for p in (st / "mods").iterdir()} - {e.filename for e in entries if e.folder == "mods"}
    client_only_files = set(srv.get("client_only_files", []))
    for e in entries:
        if e.folder != "mods" or "removed" in e.tags or e.client_only:
            continue
        shutil.copy2(e.path, out / "mods" / e.filename)
    for name in sorted(override_mods - client_only_files):
        shutil.copy2(st / "mods" / name, out / "mods" / name)

    if install and not (out / "libraries").exists():
        inst = CACHE / "forge" / f"forge-{mc}-{forge}-installer.jar"
        if not inst.exists():
            http_get(f"{FORGE_MAVEN}/{mc}-{forge}/forge-{mc}-{forge}-installer.jar", inst)
        subprocess.run([java, "-jar", str(inst), "--installServer", str(out)], check=True,
                       stdout=subprocess.DEVNULL, cwd=out)
        for junk in out.glob("*installer.jar.log"):
            junk.unlink()

    (out / "user_jvm_args.txt").write_text(
        "# JVM arguments for the server. Heap: change -Xmx to taste (4G is enough for a few players).\n"
        + "\n".join(jvm["server_args"]) + "\n")
    props = out / "server.properties"
    if not props.exists():
        props.write_text("".join(f"{k}={v}\n" for k, v in srv["properties"].items()))
    start = out / "start.sh"
    start.write_text(
        "#!/bin/sh\n"
        "# Starts the Raspberry Flavoured Optimized server. Accept the Minecraft EULA in eula.txt first.\n"
        "# Forge 1.19.2 needs Java 17: set JAVA=/path/to/java17/bin/java if `java` on PATH is a different version.\n"
        'cd "$(dirname "$0")"\n'
        f"exec \"${{JAVA:-java}}\" @user_jvm_args.txt @libraries/net/minecraftforge/forge/{mc}-{forge}/unix_args.txt \"$@\"\n")
    start.chmod(0o755)


# --------------------------------------------------------------------------- public release

INSTALL_SH = """#!/bin/sh
# Raspberry Flavoured Optimized - server installer.
# Downloads Forge {forge} and every mod in mods.lock (CurseForge / Modrinth CDNs, sha256-verified).
# Re-run it any time; files that are already present and correct are skipped.
# Needs: curl, sha256sum, and Java 17 (set JAVA=/path/to/java17/bin/java if `java` is another version).
set -eu
cd "$(dirname "$0")"
JAVA="${{JAVA:-java}}"
mkdir -p mods
tab="$(printf '\\t')"
while IFS="$tab" read -r name sha url; do
  case "$name" in ''|'#'*) continue ;; esac
  if [ -f "mods/$name" ] && echo "$sha  mods/$name" | sha256sum -c --status; then continue; fi
  echo "downloading $name"
  curl -fsSL --retry 3 -o "mods/$name.part" "$url"
  echo "$sha  mods/$name.part" | sha256sum -c --status || {{ echo "checksum mismatch: $name" >&2; exit 1; }}
  mv "mods/$name.part" "mods/$name"
done < mods.lock
if [ ! -d "libraries/net/minecraftforge/forge/{forge}" ]; then
  echo "installing Forge {forge}"
  curl -fsSL --retry 3 -o forge-installer.jar "https://maven.minecraftforge.net/net/minecraftforge/forge/{forge}/forge-{forge}-installer.jar"
  "$JAVA" -jar forge-installer.jar --installServer >/dev/null
  rm -f forge-installer.jar forge-installer.jar.log run.sh run.bat
fi
echo "Done. Read and accept the Minecraft EULA (https://aka.ms/MinecraftEULA) by putting eula=true in eula.txt, then run ./start.sh"
"""


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_release(cfg: dict, manifest: dict, entries: list[Entry], cf_zip: Path, server: Path, out: Path) -> None:
    """Public release: CF zip (mods by reference), a server pack that downloads its mods, README, checksums.

    Nothing here redistributes a mod jar unless its license allows it (pack.bundle_licenses), and the
    Minecraft server jar is never included: the server installer fetches Forge, which fetches Minecraft.
    """
    pack = cfg["pack"]
    mc = manifest["minecraft"]["version"]
    forge = manifest["minecraft"]["modLoaders"][0]["id"].removeprefix("forge-")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copy2(cf_zip, out / cf_zip.name)

    by_name = {e.filename: e for e in entries if e.folder == "mods" and "removed" not in e.tags}
    lock, bundled = [], []
    for jar in sorted((server / "mods").iterdir(), key=lambda p: p.name.lower()):
        e = by_name.get(jar.name)
        if e is not None and e.url:
            lock.append(f"{jar.name}\t{sha256(jar)}\t{e.url}")
        else:
            bundled.append(jar)  # upstream's own override jars (MIT, shipped inside the original pack too)

    base = f"{pack['name']}-{pack['version']}-server"
    with zipfile.ZipFile(out / f"{base}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for d in ("config", "defaultconfigs", "kubejs"):
            zip_dir(zf, server / d, f"{base}/{d}/")
        for jar in bundled:
            zf.write(jar, f"{base}/mods/{jar.name}")
        for name in ("server.properties", "user_jvm_args.txt", "start.sh"):
            zf.write(server / name, f"{base}/{name}")
        for name, text, mode in (("mods.lock", "# filename<TAB>sha256<TAB>url\n" + "\n".join(lock) + "\n", 0o644),
                                 ("install.sh", INSTALL_SH.format(forge=f"{mc}-{forge}"), 0o755)):
            info = zipfile.ZipInfo(f"{base}/{name}", ZIP_DATE)
            info.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(info, text, zipfile.ZIP_DEFLATED)

    # Client installer: Prism instance from the CF zip, mods fetched from CurseForge's CDN (sha256-pinned).
    refs = sorted((e for e in entries if e.pid is not None and not e.patched
                   and "removed" not in e.tags and "server_only" not in e.tags), key=lambda e: e.filename.lower())
    subst = {
        "@@PACK_NAME@@": pack["name"], "@@PACK_VERSION@@": pack["version"], "@@CF_ZIP@@": cf_zip.name,
        "@@INSTANCE_ID@@": "rf-optimized", "@@MIN_MB@@": str(cfg["jvm"]["min_mb"]),
        "@@MAX_MB@@": str(cfg["jvm"]["max_mb"]), "@@JVM_ARGS@@": " ".join(cfg["jvm"]["client_args"]),
        "@@MMC_PACK@@": mmc_pack_json(cfg, manifest),
        "@@LOCK@@": "\n".join(f"{e.folder}/{e.filename}\t{sha256(e.path)}\t{e.url}" for e in refs),
    }
    script = (ROOT / "release" / "install-client.sh").read_text()
    for k, v in subst.items():
        script = script.replace(k, v)
    if "@@" in script:
        raise SystemExit("install-client.sh: unreplaced placeholder")
    (out / "install-client.sh").write_text(script)
    (out / "install-client.sh").chmod(0o755)

    shutil.copy2(ROOT / "release" / "README.md", out / "README.md")
    (out / "CHANGES.md").write_text((DIST / "REPORT.md").read_text())
    sums = [f"{sha256(p)}  {p.name}" for p in sorted(out.iterdir()) if p.is_file() and p.suffix in (".zip", ".sh")]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")


# --------------------------------------------------------------------------- report

def report(cfg: dict, entries: list[Entry], out: Path) -> None:
    lines = [f"# Build report — {cfg['pack']['name']} {cfg['pack']['version']}", ""]
    for title, pred in (("Removed", lambda e: "removed" in e.tags),
                        ("Added", lambda e: "added" in e.tags),
                        ("Patched (shipped in overrides/mods)", lambda e: e.patched)):
        sel = [e for e in entries if pred(e)]
        lines += [f"## {title} ({len(sel)})", ""]
        lines += [f"- `{e.filename}` — {e.reason}" for e in sorted(sel, key=lambda e: e.filename.lower())] or ["- none"]
        lines.append("")
    client = sorted(e.filename for e in entries if e.client_only and "removed" not in e.tags)
    lines += [f"## Client-only (left out of the server pack) ({len(client)})", ""] + [f"- `{n}`" for n in client]
    out.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build"])
    ap.add_argument("--no-server", action="store_true", help="skip the server pack")
    ap.add_argument("--test", action="store_true", help="test build: add testkit/ harness + test JVM args to the instance")
    ap.add_argument("--java", default=os.environ.get("RF_JAVA", "java"), help="Java 17 used to install Forge server")
    ap.add_argument("--config", default="changes.toml", help="build definition (baseline.toml = stock pack + spark)")
    args = ap.parse_args()

    global CONFIG, DIST
    CONFIG = ROOT / args.config
    if CONFIG.name != "changes.toml":
        DIST = ROOT / "dist" / CONFIG.stem

    cfg = load_config()
    up, manifest, entries = resolve(cfg)
    live = [e for e in entries if "removed" not in e.tags]
    print(f"resolved {len(live)} files ({sum(1 for e in entries if 'removed' in e.tags)} removed, "
          f"{sum(1 for e in entries if 'added' in e.tags)} added)")
    if args.cmd == "fetch":
        return

    patches.apply(cfg, live, CACHE / "patched")
    st = stage(cfg, up, live)
    patches.apply_tree(cfg, st)
    ver = cfg["pack"]["version"] + ("-test" if args.test else "")
    base = f"{cfg['pack']['name']}-{ver}"
    for stale in DIST.glob(f"{cfg['pack']['name']}-*.zip"):  # outputs of earlier versions / test builds
        stale.unlink()
    write_cf_zip(cfg, manifest, st, live, DIST / f"{base}.zip")
    write_prism(cfg, manifest, st, DIST / "instance", DIST / f"{base}-prism.zip", args.test)
    if not args.no_server:
        write_server(cfg, manifest, st, live, DIST / "server", args.java, install=True)
    report(cfg, entries, DIST / "REPORT.md")
    if not args.no_server and not args.test and CONFIG.name == "changes.toml":
        write_release(cfg, manifest, live, DIST / f"{base}.zip", DIST / "server", DIST / "release")
        print(f"release -> {DIST / 'release'}")
    print(f"done -> {DIST}")


if __name__ == "__main__":
    main()
