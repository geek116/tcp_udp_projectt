# Environment

## My machine

- OS: Windows (fill in version: Settings → System → About)
- Python: (fill in: `python --version`, must be 3.10+)
- matplotlib: (fill in: `python -c "import matplotlib; print(matplotlib.__version__)"`)
- Editor: VS Code

## Network impairment method: Python proxy (not `tc netem`)

`tc netem` needs Linux. On Windows that means WSL2, which needs hardware virtualization. On this machine `wsl --status` reported:

> WSL2 is unable to start since virtualization is not enabled on this machine.

So impairment is done with `tests/proxy.py`, a user-space proxy between client and server that adds delay in both directions and randomly drops UDP datagrams.

### Limitations (state these in the report)

1. **No real TCP packet loss.** The proxy terminates TCP on both sides. By the time the proxy reads bytes, the kernel has already delivered them reliably, so dropping bytes would corrupt the stream instead of triggering TCP retransmission. Real TCP loss needs a kernel-level tool such as netem.
2. **TCP bulk throughput under delay is not realistic.** The proxy ACKs data on behalf of the server, so TCP's congestion and flow control see a ~0 ms RTT to the proxy. The 50 ms delay is added to forwarded bytes, so per-message latency (workloads B and C) is realistic, but file-transfer throughput under delay is much higher than real TCP over a 100 ms RTT path would get.
3. **Delay applies in both directions** (50 ms each way ≈ 100 ms RTT), the same as netem on loopback.
4. Timer precision on Windows: Python 3.11+ uses high-resolution timers for `time.sleep()`. On older versions, sleeps round up to ~15.6 ms, which would distort workload C.
