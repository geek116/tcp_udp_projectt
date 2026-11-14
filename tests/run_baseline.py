"""Run the UNMODIFIED AI baseline (baseline/, tag v0-ai-baseline) under the
same conditions as the final version, to show where it breaks.

Run from the repo root:
    python tests/run_baseline.py            # 5 runs per cell + warm-up
    python tests/run_baseline.py --quick

Nothing in baseline/ is edited. The baseline servers are started with their
working directory set to results/baseline_tmp/, so their received_*.bin files
land there and we can hash them. Each client call runs in a subprocess with a
timeout, because the baseline UDP client can wait forever.
Results go to results/baseline_results.csv.
"""
import argparse
import os
import csv
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "baseline"
TESTS = ROOT / "tests"
RESULTS = ROOT / "results"
WORK = RESULTS / "baseline_tmp"

SERVER_PORTS = {"tcp": 7001, "udp": 7002}
PROXY_PORTS = {"tcp": 8001, "udp": 8002}
CONDITIONS = {"clean": (0.0, 0.0), "delay50": (0.0, 0.05),
              "loss1_delay50": (0.01, 0.05), "loss5_delay50": (0.05, 0.05)}

# Small driver executed in a subprocess: imports the baseline client module
# and calls one workload, printing JSON.
DRIVER = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
mod = __import__(sys.argv[2])
workload, port, arg = sys.argv[3], int(sys.argv[4]), sys.argv[5]
if workload == "A":
    n, t = mod.file_transfer(arg, port=port)
    print(json.dumps({"bytes": n, "duration_s": t}))
elif workload == "B":
    lat = mod.request_response(count=int(arg), port=port)
    print(json.dumps({"latencies": lat}))
else:
    sent = mod.periodic(duration=float(arg), port=port)
    print(json.dumps({"sent": sent}))
"""

FIELDS = ["timestamp", "impl", "protocol", "workload", "file", "condition", "run", "warmup",
          "completed", "bytes", "duration_s", "throughput_mbps", "latency_mean_ms",
          "messages_sent", "messages_received", "received_file_bytes", "sha256_ok", "error"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else None


def start(cmd, cwd=None):
    p = subprocess.Popen([sys.executable, *cmd], cwd=cwd, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, "PYTHONUNBUFFERED": "1"})
    time.sleep(0.5)
    return p


def stop(p):
    p.terminate()
    try:
        out, _ = p.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
    return out or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--conditions", default="clean,loss5_delay50")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--timeout", type=float, default=90.0, help="per-call timeout (s) for A and C")
    ap.add_argument("--timeout-b", type=float, default=400.0, help="per-call timeout (s) for B")
    a = ap.parse_args()
    requests, periodic_s = 1000, 30.0
    files = [TESTS / "test_1MB.bin", TESTS / "test_10MB.bin"]
    if a.quick:
        a.runs, requests, periodic_s, files = 2, 200, 5.0, files[:1]
    WORK.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "baseline_results.csv"
    new = not out.exists()
    fh = open(out, "a", newline="")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new:
        w.writeheader()

    for cond in a.conditions.split(","):
        loss, delay = CONDITIONS[cond]
        for proto in ("tcp", "udp"):
            port = SERVER_PORTS[proto] if cond == "clean" else PROXY_PORTS[proto]
            jobs = [("A", f.name, str(f)) for f in files] + \
                   [("B", "", str(requests)), ("C", "", str(periodic_s))]
            for workload, fname, arg in jobs:
                for run in range(a.runs + 1):
                    # fresh server per run so its counters / files are per-run
                    srv = start([str(BASE / f"{proto}_server.py"), str(SERVER_PORTS[proto])], cwd=WORK)
                    proxy = None
                    if cond != "clean":
                        cmd = [str(TESTS / "proxy.py"), proto, "--listen", str(PROXY_PORTS[proto]),
                               "--target", str(SERVER_PORTS[proto]), "--delay", str(delay),
                               "--seed", str(1000 + run)]   # new loss pattern each run
                        if proto == "udp":
                            cmd += ["--loss", str(loss)]
                        proxy = start(cmd)
                    recv_file = WORK / f"received_{proto}.bin"
                    if recv_file.exists():
                        recv_file.unlink()
                    row = {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                           "impl": "baseline", "protocol": proto, "workload": workload,
                           "file": fname, "condition": cond, "run": run, "warmup": int(run == 0)}
                    t0 = time.perf_counter()
                    try:
                        r = subprocess.run([sys.executable, "-c", DRIVER, str(BASE), f"{proto}_client",
                                            workload, str(port), arg],
                                           capture_output=True, text=True,
                                           timeout=a.timeout_b if workload == "B" else a.timeout)
                        if r.returncode != 0:
                            row["completed"] = 0
                            row["error"] = r.stderr.strip().splitlines()[-1] if r.stderr else "crashed"
                        else:
                            res = json.loads(r.stdout.strip().splitlines()[-1])
                            row["completed"] = 1
                            if workload == "A":
                                row.update(bytes=res["bytes"], duration_s=res["duration_s"],
                                           throughput_mbps=res["bytes"] * 8 / res["duration_s"] / 1e6)
                            elif workload == "B":
                                lat = res["latencies"]
                                row.update(messages_sent=int(arg), messages_received=len(lat),
                                           latency_mean_ms=(sum(lat) / len(lat) * 1000) if lat else None)
                            else:
                                row["messages_sent"] = res["sent"]
                    except subprocess.TimeoutExpired:
                        row["completed"] = 0
                        row["error"] = "hung/too slow: no result before timeout"
                    time.sleep(max(0.3, delay * 3))   # let in-flight data drain
                    if proxy:
                        stop(proxy)
                    log = stop(srv)
                    if workload == "A":
                        row["received_file_bytes"] = recv_file.stat().st_size if recv_file.exists() else 0
                        row["sha256_ok"] = int(sha(recv_file) == sha(arg))
                    if workload == "C":
                        # baseline servers print running counts; TCP counts recv() calls, not messages
                        counts = [int(s.split()[-1]) for s in log.splitlines()
                                  if "periodic messages" in s.lower() and s.split()[-1].isdigit()]
                        if proto == "tcp":
                            counts = [int(s.split("Received ")[1].split()[0]) for s in log.splitlines()
                                      if "Received" in s] or counts
                        row["messages_received"] = max(counts) if counts else None
                    w.writerow(row)
                    fh.flush()
                    print(f"[{cond:14}] baseline {proto} {workload} {fname:14} run {run}: "
                          f"completed={row.get('completed')} sha_ok={row.get('sha256_ok', '')} "
                          f"recv={row.get('messages_received', '')} {row.get('error', '') or ''}",
                          flush=True)
    fh.close()
    print(f"\nResults appended to {out}")


if __name__ == "__main__":
    main()
