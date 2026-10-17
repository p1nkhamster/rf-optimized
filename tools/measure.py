#!/usr/bin/env python3
"""Install a test build into Prism as its own instance, run the scripted scenario, record memory.

Usage:
    python3 -I tools/measure.py <dist dir> <label> [--world DIR] [--options k:v ...]

<dist dir> is e.g. dist/ (optimized) or dist/baseline/; it must contain instance/ from a `build.py build --test`.
The instance is copied to PrismLauncher/instances/rfopt-<label>; the user's other instances are not touched.
Results go to results/<label>.json (+ class histograms).

Requires the testkit harness (kubejs scripts) to be in the instance.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRISM = Path.home() / ".local/share/PrismLauncher"
JDK = PRISM / "java/java-runtime-gamma/bin"
MARKS = ["spawn", "travel1", "travel2", "return"]


def sh(*cmd: str, timeout: int = 180) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout


def find_game_pid(mcdir: Path) -> int | None:
    # Prism passes the launch parameters over stdin, so match its entry point + working directory.
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if os.readlink(d / "cwd") == str(mcdir) and b"org.prismlauncher.EntryPoint" in (d / "cmdline").read_bytes():
                return int(d.name)
        except OSError:
            continue
    return None


class WorkspacePinner(threading.Thread):
    """Keeps every X11 window owned by the given processes on one i3 workspace (no focus change).

    i3 can't add assign/for_window rules over IPC, so windows are moved as soon as they appear.
    """

    def __init__(self, workspace: str) -> None:
        super().__init__(daemon=True)
        self.workspace = workspace
        self.pids: set[int] = set()
        self.moved: set[str] = set()
        self.enabled = shutil.which("xdotool") is not None and shutil.which("i3-msg") is not None

    def run(self) -> None:
        while self.enabled:
            for pid in list(self.pids):
                out = subprocess.run(["xdotool", "search", "--pid", str(pid)], capture_output=True, text=True).stdout
                for wid in out.split():
                    if wid not in self.moved:
                        r = subprocess.run(["i3-msg", "-q", f"[id={wid}] move container to workspace number {self.workspace}"],
                                           capture_output=True)
                        if r.returncode == 0:  # unmapped helper windows aren't managed by i3; retry those later
                            self.moved.add(wid)
            time.sleep(0.2)


def proc_status(pid: int) -> dict[str, int]:
    out = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmHWM"):
            out[k] = int(v.split()[0]) // 1024  # MiB
    return out


def heap_used_mb(pid: int) -> tuple[int, int]:
    txt = sh(str(JDK / "jcmd"), str(pid), "GC.heap_info")
    m = re.search(r"total (\d+)K, used (\d+)K", txt)
    return (int(m.group(2)) // 1024, int(m.group(1)) // 1024) if m else (-1, -1)


def nmt(pid: int) -> dict[str, int]:
    txt = sh(str(JDK / "jcmd"), str(pid), "VM.native_memory", "summary")
    out = {}
    for m in re.finditer(r"^-\s+(\S[^(]*?)\s+\(reserved=\d+KB, committed=(\d+)KB", txt, re.M):
        out[m.group(1).strip()] = int(m.group(2)) // 1024
    m = re.search(r"Total: reserved=\d+KB, committed=(\d+)KB", txt)
    if m:
        out["Total"] = int(m.group(1)) // 1024
    return out


def measure(pid: int, label: str, mark: str, outdir: Path, histo: bool) -> dict:
    before, _ = heap_used_mb(pid)
    sh(str(JDK / "jcmd"), str(pid), "GC.run")
    time.sleep(2)
    live, committed = heap_used_mb(pid)
    rec = {"mark": mark, "heap_before_gc_mb": before, "heap_live_mb": live, "heap_committed_mb": committed,
           **proc_status(pid), "native": nmt(pid)}
    if histo:
        (outdir / f"{label}-{mark}.histo").write_text(sh(str(JDK / "jcmd"), str(pid), "GC.class_histogram", timeout=300))
    print(f"  [{mark}] live={live}MB committed={committed}MB rss={rec.get('VmRSS')}MB "
          f"native-total={rec['native'].get('Total')}MB", flush=True)
    return rec


def tail_new(path: Path, pos: int) -> tuple[str, int]:
    if not path.exists():
        return "", pos
    with open(path, "rb") as fh:
        fh.seek(pos)
        data = fh.read()
    return data.decode("utf-8", "replace"), pos + len(data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist")
    ap.add_argument("label")
    ap.add_argument("--world", help="world directory to install as saves/rftest")
    ap.add_argument("--options", nargs="*", default=[], help="extra options.txt overrides, e.g. renderDistance:8")
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--workspace", default="9", help="i3 workspace the launched windows are kept on")
    args = ap.parse_args()

    src = (ROOT / args.dist / "instance").resolve()
    if not (src / "minecraft/kubejs/server_scripts/zz_rftest.js").exists():
        sys.exit(f"{src} is not a --test build")
    inst = PRISM / "instances" / f"rfopt-{args.label}"
    mc = inst / "minecraft"
    # Fresh copy every run so state from previous runs (caches, worlds) can't skew results.
    if inst.exists():
        shutil.rmtree(inst)
    shutil.copytree(src, inst)
    # -Xlog:gc writes to logs/gc.log and the JVM refuses to start if the directory is missing.
    (mc / "logs").mkdir(exist_ok=True)
    if args.world:
        shutil.copytree(args.world, mc / "saves" / "rftest")
    if args.options:
        opts = mc / "options.txt"
        lines = dict(l.split(":", 1) for l in opts.read_text().splitlines() if ":" in l) if opts.exists() else {}
        lines.update(o.split(":", 1) for o in args.options)
        opts.write_text("".join(f"{k}:{v}\n" for k, v in lines.items()))

    outdir = ROOT / "results"
    outdir.mkdir(exist_ok=True)
    result: dict = {"label": args.label, "dist": args.dist, "options": args.options, "samples": []}
    t0 = time.time()
    launcher = subprocess.Popen(["prismlauncher", "-l", inst.name, "-o", "RFTest"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    pinner = WorkspacePinner(args.workspace)
    pinner.pids.add(launcher.pid)
    pinner.start()
    pid = None
    latest, klog_srv = mc / "logs/latest.log", mc / "logs/kubejs/server.log"
    pos = {latest: 0, klog_srv: 0}
    title_at = None
    menu_done = False
    peak_rss = 0
    try:
        while time.time() - t0 < args.timeout:
            time.sleep(1)
            if pid is None:
                pid = find_game_pid(mc)
                if pid:
                    pinner.pids.add(pid)
                    print(f"game pid {pid} after {time.time() - t0:.0f}s", flush=True)
                elif time.time() - t0 > 180:
                    result["error"] = "game process never started (see the Prism console)"
                    print(result["error"], flush=True)
                    break
                continue
            if not Path(f"/proc/{pid}").exists():
                result["error"] = "game exited early"
                print("game exited early", flush=True)
                break
            peak_rss = max(peak_rss, proc_status(pid).get("VmRSS", 0))
            txt, pos[latest] = tail_new(latest, pos[latest])
            m = re.search(r"Game took ([\d.]+) seconds to start", txt)
            if m:
                result["startup_s_modernfix"] = float(m.group(1))
                print(f"  startup (ModernFix): {m.group(1)}s", flush=True)
            if re.search(r"OutOfMemoryError|Exception in thread \"Render thread\"|Reported exception", txt):
                result.setdefault("errors", []).extend(re.findall(r".*(?:OutOfMemoryError|Reported exception).*", txt))
            # title / fps markers come from the rftestkit mod, in latest.log
            if title_at is None and "RFTEST title" in txt:
                title_at = time.time()
                result["title_after_s"] = round(title_at - t0, 1)
                print(f"  title screen after {result['title_after_s']}s", flush=True)
            for f in re.findall(r"RFTEST fps (\d+) fps", txt):
                result["samples"].append({"t": round(time.time() - t0), "fps": int(f)})
            if title_at and not menu_done and time.time() - title_at > 25:
                menu_done = True
                result["menu"] = measure(pid, args.label, "menu", outdir, histo=True)
            txt, pos[klog_srv] = tail_new(klog_srv, pos[klog_srv])
            if "RFTEST error" in txt:
                result["error"] = "harness: " + re.search(r"RFTEST error.*", txt).group(0)
                print(result["error"], flush=True)
                break
            for mark, mspt in re.findall(r"RFTEST mark (\w+) mspt=([\d.]+)", txt):
                if mark == "joined":
                    result["joined_after_s"] = round(time.time() - t0, 1)
                    print(f"  joined world after {result['joined_after_s']}s", flush=True)
                elif mark in MARKS:
                    rec = measure(pid, args.label, mark, outdir, histo=mark == "travel2")
                    rec["mspt"] = float(mspt)
                    result[mark] = rec
                elif mark == "done":
                    result["done"] = True
            if result.get("done"):
                break
        else:
            result["error"] = "timeout"
    finally:
        result["peak_rss_mb"] = max(peak_rss, proc_status(pid).get("VmHWM", 0) if pid and Path(f"/proc/{pid}").exists() else 0)
        if pid and Path(f"/proc/{pid}").exists():
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                if not Path(f"/proc/{pid}").exists():
                    break
                time.sleep(1)
            else:
                os.kill(pid, signal.SIGKILL)
        try:
            os.killpg(launcher.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        gc_log = mc / "logs/gc.log"
        if gc_log.exists():
            shutil.copy2(gc_log, outdir / f"{args.label}-gc.log")
            # Leave out the GCs this tool forces through jcmd — only organic pauses count.
            forced = ("System.gc()", "Diagnostic Command", "Heap Inspection Initiated GC")
            log = "\n".join(l for l in gc_log.read_text().splitlines() if not any(f in l for f in forced))
            pauses = [float(x) for x in re.findall(r"Pause (?:Young|Full|Remark|Cleanup)[^\n]*?([\d.]+)ms$", log, re.M)]
            if pauses:
                pauses.sort()
                result["gc"] = {"pauses": len(pauses), "total_ms": round(sum(pauses)), "max_ms": pauses[-1],
                                "p99_ms": pauses[int(len(pauses) * 0.99) - 1] if len(pauses) > 1 else pauses[0],
                                "full_gcs": log.count("Pause Full")}
        shutil.copy2(latest, outdir / f"{args.label}-latest.log") if latest.exists() else None
        shots = sorted((mc / "screenshots").glob("rftest-*.png"))
        if shots:
            (outdir / f"{args.label}-shots").mkdir(exist_ok=True)
            for shot in shots:
                shutil.copy2(shot, outdir / f"{args.label}-shots" / shot.name)
        (outdir / f"{args.label}.json").write_text(json.dumps(result, indent=1))
        print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=1))


if __name__ == "__main__":
    main()
