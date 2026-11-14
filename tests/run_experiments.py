"""Measurement harness for the FINAL implementation.

Run from the repo root:
    python tests/run_experiments.py                 # full run (slow: ~40-60 min)
    python tests/run_experiments.py --quick         # smoke test (~2-3 min)

What it does:
  * starts final/tcp_server.py and final/udp_server.py
  * for each network condition, starts tests/proxy.py in front of them
    (the 'clean' condition talks to the servers directly, no proxy)
  * runs every protocol x workload  (1 warm-up + N measured runs)
  * appends EVERY run (warm-up included, flagged) to results/results.csv

Workloads (docs/workloads.md):
  A  file transfer of tests/test_1MB.bin and tests/test_10MB.bin
  B  1,000 small request/response exchanges
  C  periodic small messages, 100/s for 30 s
"""
import argparse
import csv
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "final"
TESTS = ROOT / "tests"
RESULTS = ROOT / "results"
sys.path.insert(0, str(FINAL))

import tcp_client  # noqa: E402
import udp_client  # noqa: E402

SERVER_PORTS = {"tcp": 5001, "udp": 5002}
PROXY_PORTS = {"tcp": 6001, "udp": 6002}

CONDITIONS = {
    #  name            loss   one-way delay (s)
    "clean":          (0.00, 0.000),
    "delay50":        (0.00, 0.050),
    "loss1_delay50":  (0.01, 0.050),
    "loss5_delay50":  (0.05, 0.050),
}

FIELDS = ["timestamp", "impl", "protocol", "workload", "file", "condition", "loss_pct",
          "delay_ms_each_way", "impairment", "run", "warmup", "bytes", "duration_s",
          "throughput_mbps", "latency_mean_ms", "latency_p50_ms", "latency_p95_ms",
          "latency_max_ms", "messages_sent", "messages_received", "delivery_pct",
          "retransmissions", "sha256_ok", "error"]


def start(cmd):
    p = subprocess.Popen([sys.executable, *cmd], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    if p.poll() is not None:
        raise RuntimeError(f"failed to start: {cmd}")
    return p


def stop(procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5, help="measured runs per cell (after 1 warm-up)")
    ap.add_argument("--conditions", default="clean,loss5_delay50",
                    help="comma list from: " + ",".join(CONDITIONS))
    ap.add_argument("--workloads", default="A,B,C")
    ap.add_argument("--protocols", default="tcp,udp")
    ap.add_argument("--periodic-seconds", type=float, default=30.0)
    ap.add_argument("--requests", type=int, default=1000)
    ap.add_argument("--quick", action="store_true",
                    help="2 measured runs, 5 s periodic, 200 requests, 1MB file only")
    ap.add_argument("--out", default=str(RESULTS / "results.csv"))
    a = ap.parse_args()

    files = [TESTS / "test_1MB.bin", TESTS / "test_10MB.bin"]
    if a.quick:
        a.runs, a.periodic_seconds, a.requests = 2, 5.0, 200
        files = files[:1]
    for f in files:
        if not f.exists():
            sys.exit(f"{f} missing - run: python tests/gen_test_files.py")

    clients = {"tcp": tcp_client, "udp": udp_client}
    conditions = a.conditions.split(",")
    protocols = a.protocols.split(",")
    workloads = a.workloads.split(",")

    out = Path(a.out)
    out.parent.mkdir(exist_ok=True)
    new_file = not out.exists()
    servers = [start([str(FINAL / "tcp_server.py"), "--port", str(SERVER_PORTS["tcp"])]),
               start([str(FINAL / "udp_server.py"), "--port", str(SERVER_PORTS["udp"])])]
    try:
        with open(out, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            for cond in conditions:
                loss, delay = CONDITIONS[cond]
                proxies, ports = [], dict(SERVER_PORTS)
                if cond != "clean":
                    for proto in protocols:
                        cmd = [str(TESTS / "proxy.py"), proto, "--listen", str(PROXY_PORTS[proto]),
                               "--target", str(SERVER_PORTS[proto]), "--delay", str(delay)]
                        if proto == "udp":
                            cmd += ["--loss", str(loss)]
                        proxies.append(start(cmd))
                        ports[proto] = PROXY_PORTS[proto]
                try:
                    for proto in protocols:
                        client = clients[proto]
                        port = ports[proto]
                        jobs = []
                        if "A" in workloads:
                            for f in files:
                                jobs.append(("A", f.name, lambda f=f: client.file_transfer(str(f), port=port)))
                        if "B" in workloads:
                            jobs.append(("B", "", lambda: client.request_response(count=a.requests, port=port)))
                        if "C" in workloads:
                            jobs.append(("C", "", lambda: client.periodic(duration=a.periodic_seconds, port=port)))
                        for workload, fname, job in jobs:
                            for run in range(a.runs + 1):
                                warm = run == 0
                                row = {"timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                                       "impl": "final", "protocol": proto, "workload": workload,
                                       "file": fname, "condition": cond, "loss_pct": loss * 100,
                                       "delay_ms_each_way": delay * 1000,
                                       "impairment": "none" if cond == "clean" else "python-proxy",
                                       "run": run, "warmup": int(warm)}
                                try:
                                    res = job()
                                    row.update({k: v for k, v in res.items() if k in FIELDS})
                                    if res.get("messages_sent"):
                                        row["delivery_pct"] = 100 * res["messages_received"] / res["messages_sent"]
                                except Exception as e:  # record failures, don't crash the run
                                    row["error"] = f"{type(e).__name__}: {e}"
                                w.writerow(row)
                                fh.flush()
                                label = "warm-up" if warm else f"run {run}"
                                if row.get("throughput_mbps"):
                                    summary = f"{row['throughput_mbps']:.2f} Mbit/s"
                                elif row.get("latency_mean_ms") is not None:
                                    summary = (f"mean {row['latency_mean_ms']:.2f} ms, "
                                               f"delivered {row.get('delivery_pct', 0):.1f}%")
                                else:
                                    summary = ""
                                print(f"[{cond:14}] {proto} {workload} {fname:14} {label:8} "
                                      f"{summary}  {row.get('error') or ''}", flush=True)
                finally:
                    stop(proxies)
    finally:
        stop(servers)
    print(f"\nResults appended to {out}")
    print("Next: python tests/plot_results.py")


if __name__ == "__main__":
    main()
