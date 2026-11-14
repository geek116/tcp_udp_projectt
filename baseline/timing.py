"""Timing script: runs all three workloads over TCP and UDP and reports
throughput and latency.

Start the servers first in two terminals:
    python tcp_server.py
    python udp_server.py
Then run:
    python timing.py test.bin
"""
import statistics
import sys

import tcp_client
import udp_client


def report_file(name, nbytes, seconds):
    mbps = (nbytes * 8) / seconds / 1_000_000
    print(f"{name} file transfer: {nbytes} bytes in {seconds:.3f} s -> {mbps:.2f} Mbit/s")


def report_latency(name, latencies):
    if not latencies:
        print(f"{name} request/response: no replies")
        return
    ms = [x * 1000 for x in latencies]
    print(f"{name} request/response: {len(ms)} replies, "
          f"mean {statistics.mean(ms):.3f} ms, "
          f"min {min(ms):.3f} ms, max {max(ms):.3f} ms")


def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else "test.bin"

    print("=== Workload 1: file transfer ===")
    report_file("TCP", *tcp_client.file_transfer(filename))
    report_file("UDP", *udp_client.file_transfer(filename))

    print("\n=== Workload 2: request/response ===")
    report_latency("TCP", tcp_client.request_response())
    report_latency("UDP", udp_client.request_response())

    print("\n=== Workload 3: periodic messages (10 s each) ===")
    print(f"TCP sent {tcp_client.periodic(duration=10)} messages")
    print(f"UDP sent {udp_client.periodic(duration=10)} messages")


if __name__ == "__main__":
    main()
