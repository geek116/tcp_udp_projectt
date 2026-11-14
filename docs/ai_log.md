# AI interaction log

One entry per important prompt: the exact prompt, what the AI returned, what failed, the networking knowledge needed to spot or fix it, and the change made.

All entries so far are from one Claude (claude.ai) session on 2026-11-14. Prompts are copied exactly as typed, including typos.

---

## Entry 1: Repository setup

- **Date:** 2026-11-14
- **Exact prompt:** "how to perform ot do this steps below in github  Create a shared Git repo with these folders: baseline/, final/, tests/, results/, docs/. Start the AI log (a shared doc or docs/ai_log.md)."
- **AI returned:** Steps for the GitHub web UI and the command line, plus an AI-log template.
- **What failed / was wrong:** The first AI-log template didn't have the columns the brief asks for (exact prompt, what failed, networking knowledge, change). The format was corrected in the next answer.
- **Networking knowledge needed:** None (Git only). Git knowledge: Git doesn't track empty folders, so `.gitkeep` files are needed.
- **Our change:** Created the repo and folders. Switched to this per-entry format.

---

## Entry 2: Environment check (WSL2 / netem)

- **Date:** 2026-11-14
- **Exact prompt:** "why am I getting error after install and rebooting two times" (with a screenshot of `wsl --status`)
- **AI returned:** WSL2 needs hardware virtualization (off in BIOS/UEFI) and the Virtual Machine Platform feature, and rebooting doesn't change firmware settings. In follow-ups it confirmed that virtualization is only needed for `tc netem`, not for the project.
- **What failed:** Couldn't use `tc netem` on this machine.
- **Networking knowledge needed:** `tc netem` is a Linux kernel queueing discipline, so it needs a Linux kernel. A user-space proxy can drop UDP datagrams, but it **can't** cause real TCP loss: TCP is already reliable between the client and the proxy, so dropping bytes there corrupts the stream instead of triggering TCP retransmission.
- **Our change:** Use the Python proxy (`tests/proxy.py`). Limitations are written in `docs/environment.md`.

---

## Entry 3: AI baseline (v0-ai-baseline)

- **Date:** 2026-11-14
- **Exact prompt (from the project brief):** "Write Python 3 programs for a TCP client/server and a UDP client/server that run the same three workloads: (1) transfer a file, (2) many small request/response exchanges, (3) periodic small messages. Include a timing script that reports throughput and latency. Keep it simple."
  - Asked as part of the session request: "I need to complete the whole project thing and test and make sure its working today"
- **AI returned:** `baseline/tcp_server.py`, `tcp_client.py`, `udp_server.py`, `udp_client.py`, `timing.py`. Saved unchanged and tagged `v0-ai-baseline`.
- **What failed** (found by reading every line, see `docs/baseline_review.md`, and by running `tests/run_baseline.py` through the proxy, see `results/baseline_results.csv`):
  1. **TCP file throughput is fake.** For the 1 MB file it reported ~34,500 Mbit/s, both on clean localhost and with 100 ms RTT added.
  2. **UDP file transfer corrupts the file even on clean localhost.** Only 1 of 10 clean runs (1 MB + 10 MB) had a correct SHA-256. Between 89% and 99% of the bytes arrived.
  3. **UDP file transfer hangs** if the `E` (end) datagram or the `OK` reply is lost (`recvfrom` with no timeout). With 5% loss + 100 ms RTT, 0 of 5 runs of the 10 MB file finished within 90 s, and only 44–65% of the bytes had arrived.
  4. **UDP request/response under 5% loss:** only 891 of 1,000 requests got a reply (each lost one costs a fixed 1 s timeout). Lost requests are left out of the reported latency, so the baseline's 101 ms mean looks *better* than it is. A late reply can also be counted as the answer to the next request.
  5. **TCP server treats each `recv()` as one message** (echo and periodic count).
  6. **Periodic sender drifts:** ~2,945 of 3,000 messages sent in 30 s, because `sleep(interval)` runs after the send time.
  7. **Workload C can't measure anything useful:** no sequence numbers or timestamps, so no delay figures. The UDP server reports its count only every 100 messages (2,700 under loss).
  8. **No `TCP_NODELAY`.**
  9. **Windows-specific:** UDP `recvfrom` can raise `ConnectionResetError` (WSAECONNRESET), which isn't handled.
- **Networking knowledge needed to spot or fix it:**
  1. `sendall()` returns when bytes are copied into the **local kernel send buffer**, not when the receiver has them. Delivery must be confirmed by the application (here, the server returns the SHA-256).
  2. UDP has **no flow control**. A sender in a tight loop overruns the receiver's socket buffer and the kernel silently drops datagrams. A window limits data in flight.
  3. UDP has no delivery guarantee, so **control messages need timeouts and retries** too.
  4. Timeouts should **adapt to the measured RTT** (RFC 6298: SRTT + 4·RTTVAR, Karn's rule, exponential backoff). **Sequence numbers** are needed to match replies to requests.
  5. TCP is a **byte stream with no message boundaries**, so messages need framing (length prefix).
  6. Use an absolute send schedule to avoid accumulated timing error.
  7. Measuring loss and one-way delay needs **sequence numbers and send timestamps** in each message.
  8. **Nagle's algorithm** holds small writes until earlier data is ACKed. Combined with delayed ACKs, this adds latency to small messages.
  9. On Windows, an ICMP port-unreachable caused by an earlier `sendto` surfaces as an error on the next `recvfrom`, even though UDP is connectionless.
- **Our change:** See `final/` and the table in `README.md`: length-prefix framing, `TCP_NODELAY`, timer stops on SHA-256 confirmation, UDP selective-repeat window with per-chunk ACKs and adaptive RTO, sequence numbers on every UDP message, timeouts and retries on control messages, absolute periodic schedule with seq + timestamp, Windows `ConnectionResetError` handling.

---

## Entry 4: Test environment and measurement harness

- **Date:** 2026-11-14
- **Exact prompt:** "I need to complete the whole project thing and test and make sure its working today"
- **AI returned:** `tests/gen_test_files.py`, `tests/proxy.py`, `tests/run_experiments.py`, `tests/run_baseline.py`, `tests/plot_results.py`, the `final/` implementation, and these docs.
- **What failed during testing (caught and fixed in the same session):**
  1. When run in the background, the baseline servers printed nothing, because Python block-buffers stdout when it's piped and `terminate()` lost the buffer. Fixed with `PYTHONUNBUFFERED=1`.
  2. The baseline-results parser looked for "periodic messages" but the UDP server prints "Periodic messages" (capital P). Fixed with a case-insensitive match.
  3. The first baseline timeout (30 s) reported UDP request/response as "hung". It was actually just very slow (1 s per lost packet). Gave workload B its own 400 s timeout.
  4. `run_baseline.py` restarted the proxy with the same random seed every run, so every baseline run saw the **identical** loss pattern (891/1,000 replies every time). The runs weren't independent samples. Fixed: the seed now changes per run (`--seed 1000+run`). The `results/baseline_results.csv` shipped with the code came from the run before this fix, so **re-run the baseline on your machine**.
- **Networking knowledge needed:**
  - The **proxy limitation for TCP throughput:** the proxy ACKs for the server, so TCP's congestion window sees a ~0 ms RTT to the proxy. Measured TCP file throughput under "100 ms RTT" is therefore much higher than real TCP would achieve. Latency results (B, C) are still valid.
  - Impairment is applied in **both directions** (like netem on `lo`), so 50 ms each way = 100 ms RTT.
  - With the same random seed, a "random" loss pattern repeats exactly. Independent runs need different seeds.
- **Our change:** Documented both limitations in `docs/environment.md`. They need to go in the report.

---

## Entry template (copy for new entries)

```
## Entry N: <short title>
- **Date:**
- **Exact prompt:**
- **AI returned:**
- **What failed / was wrong:**
- **Networking knowledge needed to spot or fix it:**
- **Our change:**
```
