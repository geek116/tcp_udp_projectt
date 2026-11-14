"""Make graphs and a summary table from the CSVs in results/.

Run from the repo root (after run_experiments.py and, optionally, run_baseline.py):
    python tests/plot_results.py

Warm-up runs (warmup == 1) are excluded. Bars show the mean of the measured
runs; error bars show one standard deviation.
Outputs: results/summary.csv and results/fig_*.png
"""
import csv
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"
COLORS = {"tcp": "#2a78d6", "udp": "#eb6834", "baseline": "#6250d6", "final": "#1baf7a"}
INK, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
ORDER = ["clean", "delay50", "loss1_delay50", "loss5_delay50"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": AXIS,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "legend.frameon": False,
})


def load(name):
    path = RESULTS / name
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("warmup") == "0"]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None, 0
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0), len(vals)


def grouped_bars(ax, conditions, series, title, ylabel, log=False):
    """series: {label: (color, {condition: (mean, std)})}"""
    n = len(series)
    width = 0.8 / max(n, 1)
    for i, (label, (color, data)) in enumerate(series.items()):
        xs, ms, ss = [], [], []
        for j, c in enumerate(conditions):
            m, s = data.get(c, (None, None))
            if m is None:
                continue
            xs.append(j - 0.4 + width * (i + 0.5))
            ms.append(m)
            ss.append(s or 0)
        ax.bar(xs, ms, width * 0.92, yerr=ss, color=color, label=label,
               error_kw={"ecolor": INK, "elinewidth": 0.8, "capsize": 2})
        for x, m, sd in zip(xs, ms, ss):
            label_txt = f"{m:,.0f}" if m >= 100 else f"{m:.3g}"
            ax.annotate(label_txt, (x, m + sd), xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7.5, color=MUTED)
    ax.set_xticks(range(len(conditions)))
    ax.set_xticklabels(conditions)
    ax.set_title(title, loc="left", color=INK, pad=24)
    ax.set_ylabel(ylabel)
    if log:
        ax.set_yscale("log")
    ax.grid(axis="x", visible=False)
    ax.margins(y=0.12)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=n, fontsize=9,
              handlelength=1.2, borderaxespad=0)


def main():
    rows = load("results.csv")
    if not rows:
        raise SystemExit("results/results.csv not found - run tests/run_experiments.py first")
    conditions = [c for c in ORDER if any(r["condition"] == c for r in rows)]

    # ---- summary table --------------------------------------------------
    metrics = ["duration_s", "throughput_mbps", "latency_mean_ms", "latency_p95_ms",
               "delivery_pct", "retransmissions"]
    groups = defaultdict(list)
    for r in rows:
        groups[(r["protocol"], r["workload"], r["file"], r["condition"])].append(r)
    with open(RESULTS / "summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["protocol", "workload", "file", "condition", "runs", "sha256_ok_runs", "errors"]
                   + [f"{m}_{k}" for m in metrics for k in ("mean", "std")])
        for key in sorted(groups, key=lambda k: (k[1], k[2], ORDER.index(k[3]) if k[3] in ORDER else 9, k[0])):
            g = groups[key]
            line = list(key) + [len(g), sum(r["sha256_ok"] == "True" for r in g),
                                sum(bool(r["error"]) for r in g)]
            for m in metrics:
                mean, std, _ = stats([num(r[m]) for r in g])
                line += [f"{mean:.4f}" if mean is not None else "", f"{std:.4f}" if std is not None else ""]
            w.writerow(line)

    def collect(workload, metric, file=""):
        out = {}
        for proto in ("tcp", "udp"):
            d = {}
            for c in conditions:
                m, s, n = stats([num(r[metric]) for r in rows if r["protocol"] == proto
                                 and r["workload"] == workload and r["condition"] == c
                                 and (not file or r["file"] == file) and not r["error"]])
                if n:
                    d[c] = (m, s)
            if d:
                out[proto.upper()] = (COLORS[proto], d)
        return out

    # ---- Workload A: throughput -----------------------------------------
    files = sorted({r["file"] for r in rows if r["workload"] == "A"},
                   key=lambda f: int("".join(ch for ch in f if ch.isdigit()) or 0))
    if files:
        fig, axes = plt.subplots(1, len(files), figsize=(5.5 * len(files), 4), squeeze=False)
        for ax, fname in zip(axes[0], files):
            grouped_bars(ax, conditions, collect("A", "throughput_mbps", fname),
                         f"Workload A - file transfer ({fname})", "Throughput (Mbit/s, log scale)", log=True)
        fig.tight_layout()
        fig.savefig(RESULTS / "fig_A_throughput.png", dpi=150)
        plt.close(fig)

    # ---- Workload B: request/response latency ----------------------------
    if any(r["workload"] == "B" for r in rows):
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        grouped_bars(axes[0], conditions, collect("B", "latency_mean_ms"),
                     "Workload B - mean round-trip time", "RTT (ms)")
        grouped_bars(axes[1], conditions, collect("B", "latency_p95_ms"),
                     "Workload B - 95th percentile RTT", "RTT (ms)")
        fig.tight_layout()
        fig.savefig(RESULTS / "fig_B_latency.png", dpi=150)
        plt.close(fig)

    # ---- Workload C: periodic delivery + one-way delay -------------------
    if any(r["workload"] == "C" for r in rows):
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        grouped_bars(axes[0], conditions, collect("C", "delivery_pct"),
                     "Workload C - messages delivered", "Delivered (%)")
        axes[0].set_ylim(0, 110)
        grouped_bars(axes[1], conditions, collect("C", "latency_mean_ms"),
                     "Workload C - mean one-way delay", "Delay (ms)")
        fig.tight_layout()
        fig.savefig(RESULTS / "fig_C_periodic.png", dpi=150)
        plt.close(fig)

    # ---- Baseline vs final: file integrity --------------------------------
    base = load("baseline_results.csv")
    if base:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
        for ax, proto in zip(axes, ("tcp", "udp")):
            series = {}
            for impl, src in (("baseline", base), ("final", rows)):
                d = {}
                for c in conditions:
                    g = [r for r in src if r["protocol"] == proto and r["workload"] == "A"
                         and r["condition"] == c]
                    if g:
                        ok = sum(r["sha256_ok"] in ("1", "True") for r in g)
                        d[c] = (100 * ok / len(g), 0)
                if d:
                    series[impl.capitalize()] = (COLORS[impl], d)
            grouped_bars(ax, conditions, series,
                         f"{proto.upper()} file transfer - runs with correct SHA-256", "Runs correct (%)")
            ax.set_ylim(0, 115)
        fig.tight_layout()
        fig.savefig(RESULTS / "fig_baseline_vs_final_integrity.png", dpi=150)
        plt.close(fig)

    print("Wrote", RESULTS / "summary.csv")
    for p in sorted(RESULTS.glob("fig_*.png")):
        print("Wrote", p)


if __name__ == "__main__":
    main()
