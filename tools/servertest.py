#!/usr/bin/env python3
"""Boot a built server pack headless, pre-generate a test world, record timings/memory, check the log.

Usage: python3 -I tools/servertest.py <dist dir> <label> [--radius 256]

Runs a throwaway copy in .cache/run/<label>-server (the EULA is accepted in that copy only; dist/server is
left untouched). The generated world is kept in results/<label>-world for the client test.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JDK = Path.home() / ".local/share/PrismLauncher/java/java-runtime-gamma/bin"
SEED = "8675309"


def heap(pid: int) -> tuple[int, int]:
    # The server runs with -XX:+DisableExplicitGC, so GC.run is a no-op; a class histogram forces a full GC.
    subprocess.run([str(JDK / "jcmd"), str(pid), "GC.class_histogram"], capture_output=True, timeout=300)
    time.sleep(2)
    txt = subprocess.run([str(JDK / "jcmd"), str(pid), "GC.heap_info"], capture_output=True, text=True).stdout
    m = re.search(r"total (\d+)K, used (\d+)K", txt)
    rss = next(int(l.split()[1]) // 1024 for l in Path(f"/proc/{pid}/status").read_text().splitlines() if l.startswith("VmRSS"))
    return (int(m.group(2)) // 1024 if m else -1), rss


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dist")
    ap.add_argument("label")
    ap.add_argument("--radius", type=int, default=256)
    ap.add_argument("--settle", type=int, default=90, help="seconds to wait after pregen before re-measuring")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()

    src = ROOT / args.dist / "server"
    run = ROOT / ".cache/run" / f"{args.label}-server"
    shutil.rmtree(run, ignore_errors=True)
    shutil.copytree(src, run, symlinks=True)
    (run / "eula.txt").write_text("eula=true\n")
    props = run / "server.properties"
    lines = dict(l.split("=", 1) for l in props.read_text().splitlines() if "=" in l and not l.startswith("#"))
    lines.update({"level-name": "rftest", "level-seed": SEED, "online-mode": "false", "server-port": "25599"})
    props.write_text("".join(f"{k}={v}\n" for k, v in lines.items()))
    forge_args = next(run.glob("libraries/net/minecraftforge/forge/*/unix_args.txt"))

    t0 = time.time()
    p = subprocess.Popen([str(JDK / "java"), "@user_jvm_args.txt", f"@{forge_args.relative_to(run)}", "nogui"],
                         cwd=run, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines_q: queue.Queue[str] = queue.Queue()
    (ROOT / "results").mkdir(exist_ok=True)
    console = open(ROOT / "results" / f"{args.label}-server-console.txt", "w")

    def pump() -> None:
        for line in p.stdout:
            console.write(line)
            lines_q.put(line)
        console.close()

    threading.Thread(target=pump, daemon=True).start()

    def wait_for(pattern: str, limit: float) -> re.Match | None:
        end = time.time() + limit
        while time.time() < end:
            try:
                line = lines_q.get(timeout=1)
            except queue.Empty:
                if p.poll() is not None:
                    return None
                continue
            m = re.search(pattern, line)
            if m:
                return m
        return None

    res: dict = {"label": args.label}
    try:
        if not wait_for(r"Done \(([\d.]+)s\)!", args.timeout):
            res["error"] = "server did not finish starting"
            return
        res["startup_s"] = round(time.time() - t0, 1)
        res["idle_live_heap_mb"], res["idle_rss_mb"] = heap(p.pid)
        print(f"started in {res['startup_s']}s, idle live heap {res['idle_live_heap_mb']}MB rss {res['idle_rss_mb']}MB", flush=True)

        has_chunky = any(run.glob("mods/Chunky-*.jar"))
        if has_chunky:
            for cmd in ("chunky world minecraft:overworld", "chunky center 0 0", f"chunky radius {args.radius}",
                        "chunky start", "chunky confirm"):
                p.stdin.write(cmd + "\n")
                p.stdin.flush()
            t1 = time.time()
            m = wait_for(r"Task finished for minecraft:overworld|Task (?:stopped|cancelled)", args.timeout)
            res["pregen_s"] = round(time.time() - t1, 1) if m else None
            res["pregen_chunks"] = (args.radius * 2 // 16 + 1) ** 2
            res["after_pregen_live_heap_mb"], res["after_pregen_rss_mb"] = heap(p.pid)
            print(f"pregen r={args.radius} in {res['pregen_s']}s, live heap {res['after_pregen_live_heap_mb']}MB", flush=True)
            # Generated chunks stay loaded / queued for saving for a while; measure again once they settle.
            time.sleep(args.settle)
            res["settled_live_heap_mb"], res["settled_rss_mb"] = heap(p.pid)
            print(f"after {args.settle}s settle: live heap {res['settled_live_heap_mb']}MB rss {res['settled_rss_mb']}MB", flush=True)
        p.stdin.write("stop\n")
        p.stdin.flush()
        p.wait(timeout=300)
    finally:
        if p.poll() is None:
            p.kill()
        log = (run / "logs/latest.log").read_text(errors="replace") if (run / "logs/latest.log").exists() else ""
        res["errors"] = sorted(set(re.findall(r"^\[[^\]]+\] \[[^\]]+/(?:ERROR|FATAL)\] \[([^\]]+)\]", log, re.M)))
        res["mixin_failures"] = re.findall(r"Mixin apply (?:for mod \S+ )?failed.*", log)[:20]
        out = ROOT / "results"
        out.mkdir(exist_ok=True)
        shutil.copy2(run / "logs/latest.log", out / f"{args.label}-server.log") if log else None
        if (run / "rftest").exists():
            dst = out / f"{args.label}-world"
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(run / "rftest", dst)
        (out / f"{args.label}-server.json").write_text(json.dumps(res, indent=1))
        print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
