"""TCP client for the three workloads (final version).

Each function returns a dict of measurements used by tests/run_experiments.py.
"""
import json
import socket
import struct
import time

from common import (HOST, TCP_PORT, latency_summary, recv_exact, recv_msg,
                    send_msg, sha256_file)

PERIODIC_HDR = struct.Struct("!Id")


def _connect(host, port):
    sock = socket.create_connection((host, port), timeout=120)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


def file_transfer(path, host=HOST, port=TCP_PORT):
    """Send a file; stop the clock only when the server confirms the hash.

    Stopping at sendall() (as the baseline did) only measures how fast bytes
    were copied into the local kernel buffer, not delivery.
    """
    with open(path, "rb") as f:
        data = f.read()
    expected = sha256_file(path)
    start = time.perf_counter()
    sock = _connect(host, port)          # include the 3-way handshake
    sock.sendall(b"F" + struct.pack("!Q", len(data)))
    sock.sendall(data)
    digest = recv_exact(sock, 32)
    duration = time.perf_counter() - start
    sock.close()
    return {"bytes": len(data), "duration_s": duration,
            "throughput_mbps": len(data) * 8 / duration / 1e6,
            "sha256_ok": digest == expected,
            "messages_sent": None, "messages_received": None, "retransmissions": None}


def request_response(count=1000, size=64, host=HOST, port=TCP_PORT):
    sock = _connect(host, port)
    sock.sendall(b"R")
    payload = b"x" * size
    latencies = []
    ok = True
    start = time.perf_counter()
    for i in range(count):
        t0 = time.perf_counter()
        send_msg(sock, payload)
        reply = recv_msg(sock)          # reads exactly one whole message
        if reply != payload:
            ok = False
            break
        latencies.append(time.perf_counter() - t0)
    duration = time.perf_counter() - start
    sock.close()
    out = {"bytes": count * size, "duration_s": duration, "throughput_mbps": None,
           "sha256_ok": None, "messages_sent": count, "messages_received": len(latencies),
           "retransmissions": None, "data_ok": ok}
    out.update(latency_summary(latencies))
    return out


def periodic(rate=100, duration=30.0, size=64, host=HOST, port=TCP_PORT):
    sock = _connect(host, port)
    sock.sendall(b"P")
    pad = b"x" * max(0, size - PERIODIC_HDR.size)
    interval = 1.0 / rate
    count = int(rate * duration)
    start = time.perf_counter()
    late_sends = 0
    for seq in range(count):
        # absolute schedule avoids drift from accumulated sleep() error
        target = start + seq * interval
        now = time.perf_counter()
        if target > now:
            time.sleep(target - now)
        elif now - target > interval:
            late_sends += 1
        send_msg(sock, PERIODIC_HDR.pack(seq, time.perf_counter()) + pad)
    send_msg(sock, b"")  # end marker
    stats = json.loads(recv_msg(sock))
    total = time.perf_counter() - start
    sock.close()
    out = {"bytes": count * size, "duration_s": total, "throughput_mbps": None,
           "sha256_ok": None, "messages_sent": count,
           "messages_received": stats["received"], "retransmissions": None,
           "late_sends": late_sends}
    out.update(latency_summary(stats["delays"]))
    return out
