# TCP vs UDP: AI baseline and improved implementation

Compares TCP and UDP on three workloads (file transfer, request/response, periodic messages) under clean and impaired network conditions. Starts from an unmodified AI-generated baseline and documents what failed, why, and how it was fixed.

## Repository layout

| Folder | Contents |
|---|---|
| `baseline/` | AI output, **unmodified** (git tag `v0-ai-baseline`) |
| `final/` | Improved implementation: `common.py`, `tcp_server.py`, `tcp_client.py`, `udp_server.py`, `udp_client.py` |
| `tests/` | Test files and hashes, impairment proxy, measurement harness, plotting |
| `results/` | Raw CSVs (every run), `summary.csv`, graphs `fig_*.png` |
| `docs/` | AI log, baseline review, workloads, environment, report notes |

## Requirements

Python 3.10+ (3.11+ recommended on Windows for accurate sleep timing) and matplotlib (`pip install matplotlib`). No other packages.

## How to run (Windows PowerShell, from the repo root)

```powershell
# 1. test files + SHA-256 hashes (once)
python tests/gen_test_files.py

# 2. quick smoke test of the final version (~3 min)
python tests/run_experiments.py --quick --out results/quick_test.csv

# 3. full experiment: 1 warm-up + 5 measured runs per cell (~35-45 min)
python tests/run_experiments.py

# 4. run the unmodified baseline under the same conditions (~45-60 min)
python tests/run_baseline.py

# 5. graphs + summary table
python tests/plot_results.py
```

Optional extra conditions:
`python tests/run_experiments.py --conditions clean,delay50,loss1_delay50,loss5_delay50`

If Windows Firewall asks about Python, click **Allow**. Everything uses 127.0.0.1 only.

To run things by hand, start each in its own terminal:

```powershell
python final/tcp_server.py
python final/udp_server.py
python tests/proxy.py udp --listen 6002 --target 5002 --loss 0.05 --delay 0.05
python tests/proxy.py tcp --listen 6001 --target 5001 --delay 0.05
```

## What changed from the baseline (summary)

See `docs/ai_log.md` for the full record and `docs/baseline_review.md` for the line-by-line review.

| Problem in baseline | Networking reason | Fix in `final/` |
|---|---|---|
| TCP file timer stops at `sendall()` (reported ~34,500 Mbit/s at 100 ms RTT) | `sendall()` returns when data is in the local kernel buffer, not when it's delivered | Timer stops when the server returns the SHA-256 of what it received |
| TCP `recv()` treated as one message | TCP is a byte stream with no message boundaries | 4-byte length prefix framing (`send_msg`/`recv_msg`) |
| No `TCP_NODELAY` | Nagle's algorithm plus delayed ACK can hold small writes back | `TCP_NODELAY` on both ends |
| UDP file corrupt in 9 of 10 runs even on clean localhost | No flow control: sender overruns the receive buffer | Sliding window (256 chunks), larger socket buffers |
| UDP file has no sequence numbers or retransmission | UDP gives no delivery or ordering guarantees | Per-chunk sequence numbers, ACKs, selective repeat, RFC 6298 RTO, SHA-256 check |
| UDP file blocks forever if `END`/`OK` is lost | Control messages can be lost too | Every control exchange has timeout + retry |
| UDP request/response: late reply matched to wrong request | No sequence numbers | Sequence number in each request/reply; stale replies ignored |
| Fixed 1 s UDP timeout | Should adapt to RTT | Adaptive RTO (SRTT + 4·RTTVAR, Karn's rule, exponential backoff) |
| Periodic: can't measure loss or delay, sends drift | No seq/timestamps; `sleep(interval)` accumulates error | Seq + timestamp per message, absolute send schedule, receiver reports delivery and one-way delay |
| Windows UDP `ConnectionResetError` | Windows reports ICMP port-unreachable on the next `recvfrom` | Caught and ignored (`common.udp_recv`) |
