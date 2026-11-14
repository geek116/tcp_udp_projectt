"""UDP client for the three workloads (final version).

Reliability is added in the application, because UDP has none:
  * file transfer   : selective-repeat sliding window. Each chunk has a
                      sequence number and is ACKed individually; unACKed
                      chunks are resent after a retransmission timeout (RTO).
  * request/response: stop-and-wait. Resend the request if no reply within
                      the RTO; match replies by sequence number so a late
                      reply to an old request is not mistaken for a new one.
  * periodic        : NO retransmission, on purpose. For real-time data
                      (e.g. sensor readings, game state) a resent old message
                      is useless, so we measure loss instead of hiding it.

RTO follows RFC 6298 (SRTT/RTTVAR, Karn's rule: never take an RTT sample
from a retransmitted packet, double the RTO on timeout).
"""
import json
import random
import socket
import struct
import time

from common import HOST, UDP_PORT, latency_summary, make_udp_socket, sha256_file

START = struct.Struct("!cIQI")
DATA = struct.Struct("!cII")
SESS = struct.Struct("!cI")
REQ = struct.Struct("!cI")
PER = struct.Struct("!cIId")

CHUNK = 1200        # stays under a 1500-byte Ethernet MTU with IP/UDP headers
WINDOW = 256        # max chunks in flight
MIN_RTO, MAX_RTO, INITIAL_RTO = 0.05, 2.0, 0.3
GIVE_UP_S = 600


class RTOEstimator:
    def __init__(self):
        self.srtt = None
        self.rttvar = None
        self.rto = INITIAL_RTO

    def sample(self, rtt):
        if self.srtt is None:
            self.srtt, self.rttvar = rtt, rtt / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - rtt)
            self.srtt = 0.875 * self.srtt + 0.125 * rtt
        self.rto = min(MAX_RTO, max(MIN_RTO, self.srtt + 4 * self.rttvar))

    def backoff(self):
        self.rto = min(MAX_RTO, self.rto * 2)


def _request_until(sock, addr, packet, accept, est, deadline):
    """Send `packet` until a reply satisfying accept(data) arrives."""
    retrans = 0
    while time.perf_counter() < deadline:
        sent_at = time.perf_counter()
        sock.sendto(packet, addr)
        sock.settimeout(est.rto)
        while True:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                break
            except ConnectionResetError:
                continue
            if accept(data):
                if retrans == 0:
                    est.sample(time.perf_counter() - sent_at)
                return data, retrans
            remaining = est.rto - (time.perf_counter() - sent_at)
            if remaining <= 0:
                break
            sock.settimeout(remaining)
        retrans += 1
        est.backoff()
    raise TimeoutError("no reply from server")


def file_transfer(path, host=HOST, port=UDP_PORT):
    addr = (host, port)
    with open(path, "rb") as f:
        data = f.read()
    expected = sha256_file(path)
    n = (len(data) + CHUNK - 1) // CHUNK
    sess = random.getrandbits(32)
    sock = make_udp_socket()
    est = RTOEstimator()
    start = time.perf_counter()
    deadline = start + GIVE_UP_S

    _, retrans = _request_until(sock, addr, START.pack(b"S", sess, len(data), n),
                                lambda d: d == SESS.pack(b"a", sess), est, deadline)

    acked = bytearray(n)
    acked_count = 0
    inflight = {}          # seq -> (last_send_time, was_retransmitted)
    next_seq = 0
    sock.settimeout(0.002)
    last_timer_check = 0.0

    def send_chunk(seq):
        sock.sendto(DATA.pack(b"D", sess, seq) + data[seq * CHUNK:(seq + 1) * CHUNK], addr)

    while acked_count < n:
        if time.perf_counter() > deadline:
            raise TimeoutError("file transfer gave up")
        while next_seq < n and len(inflight) < WINDOW:
            send_chunk(next_seq)
            inflight[next_seq] = (time.perf_counter(), False)
            next_seq += 1
        # drain whatever ACKs are waiting
        try:
            while True:
                pkt, _ = sock.recvfrom(65535)
                if len(pkt) == DATA.size and pkt[:1] == b"k":
                    _, s, seq = DATA.unpack(pkt)
                    if s == sess and not acked[seq]:
                        acked[seq] = 1
                        acked_count += 1
                        sent_at, was_rtx = inflight.pop(seq, (None, True))
                        if not was_rtx:
                            est.sample(time.perf_counter() - sent_at)
                sock.settimeout(0)
        except (socket.timeout, BlockingIOError, ConnectionResetError):
            pass
        sock.settimeout(0.002)
        now = time.perf_counter()
        if now - last_timer_check >= 0.005:
            last_timer_check = now
            timed_out = False
            for seq, (sent_at, _) in list(inflight.items()):
                if now - sent_at > est.rto:
                    send_chunk(seq)
                    inflight[seq] = (now, True)
                    retrans += 1
                    timed_out = True
            if timed_out:
                est.backoff()

    reply, r = _request_until(sock, addr, SESS.pack(b"F", sess),
                              lambda d: d[:SESS.size] == SESS.pack(b"h", sess), est, deadline)
    retrans += r
    duration = time.perf_counter() - start
    sock.close()
    return {"bytes": len(data), "duration_s": duration,
            "throughput_mbps": len(data) * 8 / duration / 1e6,
            "sha256_ok": reply[SESS.size:] == expected,
            "messages_sent": n, "messages_received": n, "retransmissions": retrans}


def request_response(count=1000, size=64, host=HOST, port=UDP_PORT):
    addr = (host, port)
    sock = make_udp_socket()
    est = RTOEstimator()
    payload = b"x" * max(0, size - REQ.size)
    latencies, retrans, failed = [], 0, 0
    start = time.perf_counter()
    for seq in range(count):
        pkt = REQ.pack(b"Q", seq) + payload
        want = REQ.pack(b"q", seq) + payload
        t0 = time.perf_counter()
        try:
            _, r = _request_until(sock, addr, pkt, lambda d: d == want, est, t0 + 30)
        except TimeoutError:
            failed += 1
            continue
        retrans += r
        latencies.append(time.perf_counter() - t0)   # includes retransmission wait
    duration = time.perf_counter() - start
    sock.close()
    out = {"bytes": count * size, "duration_s": duration, "throughput_mbps": None,
           "sha256_ok": None, "messages_sent": count, "messages_received": len(latencies),
           "retransmissions": retrans, "data_ok": failed == 0}
    out.update(latency_summary(latencies))
    return out


def periodic(rate=100, duration=30.0, size=64, host=HOST, port=UDP_PORT):
    addr = (host, port)
    sock = make_udp_socket()
    sess = random.getrandbits(32)
    pad = b"x" * max(0, size - PER.size)
    interval = 1.0 / rate
    count = int(rate * duration)
    start = time.perf_counter()
    late_sends = 0
    for seq in range(count):
        target = start + seq * interval
        now = time.perf_counter()
        if target > now:
            time.sleep(target - now)
        elif now - target > interval:
            late_sends += 1
        sock.sendto(PER.pack(b"M", sess, seq, time.perf_counter()) + pad, addr)
    time.sleep(0.5)   # let delayed datagrams arrive before asking for stats
    est = RTOEstimator()
    reply, _ = _request_until(sock, addr, SESS.pack(b"T", sess),
                              lambda d: d[:SESS.size] == SESS.pack(b"t", sess), est,
                              time.perf_counter() + 30)
    stats = json.loads(reply[SESS.size:])
    total = time.perf_counter() - start
    sock.close()
    out = {"bytes": count * size, "duration_s": total, "throughput_mbps": None,
           "sha256_ok": None, "messages_sent": count, "messages_received": stats["received"],
           "retransmissions": 0, "late_sends": late_sends}
    out.update({k: v for k, v in stats.items() if k.startswith("latency")})
    return out
