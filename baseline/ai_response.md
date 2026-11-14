# AI baseline: prompt and response record

**Tool:** Claude (claude.ai), 2026-11-14

**Exact prompt:**

> Write Python 3 programs for a TCP client/server and a UDP client/server that run the same three workloads: (1) transfer a file, (2) many small request/response exchanges, (3) periodic small messages. Include a timing script that reports throughput and latency. Keep it simple.

**Response:** the five files in this folder, saved exactly as returned:

| File | Purpose |
|------|---------|
| `tcp_server.py` | TCP server; first byte selects workload (F/R/P) |
| `tcp_client.py` | TCP client functions `file_transfer`, `request_response`, `periodic` |
| `udp_server.py` | UDP server; first byte of each datagram selects action |
| `udp_client.py` | UDP client functions, same three workloads |
| `timing.py` | Runs all workloads over TCP and UDP and prints throughput/latency |

How to run (as given by the AI): start `python tcp_server.py` and `python udp_server.py` in two terminals, then `python timing.py test.bin`.

**Do not edit anything in this folder.** It is tagged `v0-ai-baseline`, and every comparison depends on it staying unchanged. Improvements go in `final/`.
