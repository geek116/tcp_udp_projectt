# Results notes (draft for the report)

Numbers are means of 5 measured runs (warm-up excluded) from `results/sample_linux_run/summary.csv`. Conditions: **clean** = direct on 127.0.0.1; **impaired** = Python proxy with 50 ms delay each way (≈100 ms RTT), plus 5% UDP loss each way. TCP gets delay only (see `docs/environment.md`).

> These numbers came from a Linux test machine. **Re-run on your own Windows machine** (`README.md` → How to run) and update this file with your numbers before submitting. The pattern should be the same; the absolute values will differ.

## Baseline vs final

| Check | Baseline (AI, unmodified) | Final |
|---|---|---|
| TCP file transfer, 1 MB, impaired: reported throughput | ~34,500 Mbit/s (impossible: measures kernel buffer copy) | 77.6 Mbit/s (≈ 1 MB / 100 ms, delivery confirmed) |
| UDP file transfer, clean: runs with correct SHA-256 | 1 of 10 | 10 of 10 |
| UDP file transfer, 10 MB, impaired | 0 of 5 finished (hung); 44–65% of bytes arrived | 5 of 5 correct, 4.6 s, ~914 retransmissions |
| UDP request/response, impaired: replies | 891 of 1,000 (lost ones silently dropped from latency) | 1,000 of 1,000 |
| Periodic messages sent in 30 s (target 3,000) | ~2,945 (sleep drift) | 3,000 |
| Periodic: delivery % and one-way delay measured? | No | Yes |

## Final implementation: TCP vs UDP

### Workload A: file transfer (`results/sample_linux_run/fig_A_throughput.png`)

| | Clean | Impaired |
|---|---|---|
| TCP 1 MB | 6,438 Mbit/s | 77.6 Mbit/s |
| UDP 1 MB | 1,940 Mbit/s | 6.8 Mbit/s (≈99 retransmissions) |
| TCP 10 MB | 8,525 Mbit/s | 724 Mbit/s |
| UDP 10 MB | 1,953 Mbit/s | 18.0 Mbit/s (≈914 retransmissions) |

- **Clean:** TCP is 3–4× faster. The kernel does segmentation, ACKs and flow control in C, while the UDP reliability layer is Python handling one 1,200-byte datagram and one ACK at a time.
- **Impaired:** UDP pays for every loss with a timeout (RTO ≥ ~100 ms) and is limited by a 256-chunk window per RTT. Retransmissions ≈ 11% of chunks, consistent with 5% data loss + 5% ACK loss (1 − 0.95² ≈ 9.75%).
- **Caveat:** impaired TCP throughput is inflated by the proxy (it ACKs on the server's behalf, so TCP's window never sees the 100 ms RTT, and there's no TCP loss). Don't claim TCP would do 724 Mbit/s over a real 100 ms, 5%-loss path. With real loss, TCP's congestion control would cut its window sharply.

### Workload B: request/response (`results/sample_linux_run/fig_B_latency.png`)

| | Clean mean | Impaired mean | Impaired p95 |
|---|---|---|---|
| TCP | 0.036 ms | 101.0 ms | 101.3 ms |
| UDP | 0.029 ms | 115.6 ms | 203.6 ms |

- Clean: both are tens of microseconds. UDP is slightly faster (no stream bookkeeping). This shows why localhost without impairment makes TCP and UDP look identical.
- Impaired: the mean ≈ RTT (100 ms). UDP's **p95 is ~2× RTT** because ~11% of exchanges lose the request or the reply and wait one RTO before retrying. TCP shows no tail here only because the proxy doesn't drop TCP; under real loss TCP would also show retransmission stalls, typically longer, since TCP's minimum RTO is often 200 ms or more.

### Workload C: periodic messages (`results/sample_linux_run/fig_C_periodic.png`)

| | Delivered (impaired) | One-way delay (impaired) |
|---|---|---|
| TCP | 100% | 50.3 ms |
| UDP | 94.9% | 50.3 ms |

- UDP delivers ~95%, matching the 5% loss, and **every delivered message arrives on time**.
- For real-time data, a late message is often worthless. UDP lets the application choose to drop instead of wait, so the final version deliberately does **not** retransmit periodic messages. With real TCP loss, one lost segment would block every later message until it's retransmitted (head-of-line blocking), adding delay spikes to many messages instead of losing one.

## Points to make in the report

1. On localhost with no impairment, TCP and UDP look nearly the same. Impairment is essential.
2. Reliability isn't free: the UDP file transfer had to re-implement sequence numbers, ACKs, windows and RTO, and it's still slower than kernel TCP.
3. Choose by workload: bulk data → TCP; latency-sensitive periodic data → UDP (accept loss, avoid head-of-line blocking); request/response → either, but UDP needs app-level retry and sequence numbers.
4. Limitations: user-space proxy (no TCP loss, TCP throughput under delay inflated), loopback only, one machine, impairment in both directions, Python overhead dominates clean throughput.
