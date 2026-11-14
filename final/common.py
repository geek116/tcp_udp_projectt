"""Shared helpers for the final TCP/UDP implementations."""
import hashlib
import socket
import statistics
import struct

TCP_PORT = 5001
UDP_PORT = 5002
HOST = "127.0.0.1"

# --- TCP message framing -------------------------------------------------
# TCP is a byte stream: one send() does not equal one recv(). Every
# application message is prefixed with a 4-byte big-endian length so the
# receiver knows exactly where each message ends.
LEN = struct.Struct("!I")


def recv_exact(sock, n):
    """Read exactly n bytes, or return None if the peer closed first."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def send_msg(sock, payload):
    sock.sendall(LEN.pack(len(payload)) + payload)


def recv_msg(sock):
    header = recv_exact(sock, LEN.size)
    if header is None:
        return None
    (length,) = LEN.unpack(header)
    return recv_exact(sock, length)


# --- UDP helpers ---------------------------------------------------------
UDP_SOCK_BUF = 4 * 1024 * 1024


def make_udp_socket(bind=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_SOCK_BUF)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, UDP_SOCK_BUF)
    if bind:
        s.bind(bind)
    return s


def udp_recv(sock):
    """recvfrom that survives Windows' WSAECONNRESET.

    On Windows, if a datagram we sent earlier triggered an ICMP 'port
    unreachable', the NEXT recvfrom raises ConnectionResetError even though
    UDP is connectionless. Ignore it and keep reading.
    """
    while True:
        try:
            return sock.recvfrom(65535)
        except ConnectionResetError:
            continue


# --- misc ----------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.digest()


def latency_summary(latencies_s):
    """Return mean/p50/p95/max in milliseconds."""
    if not latencies_s:
        return {"latency_mean_ms": None, "latency_p50_ms": None,
                "latency_p95_ms": None, "latency_max_ms": None}
    ms = sorted(x * 1000 for x in latencies_s)
    p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
    return {"latency_mean_ms": statistics.mean(ms),
            "latency_p50_ms": statistics.median(ms),
            "latency_p95_ms": p95,
            "latency_max_ms": ms[-1]}
