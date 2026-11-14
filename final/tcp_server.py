"""TCP server for the three workloads (final version).

Run: python final/tcp_server.py [--port 5001]

Protocol (all messages length-prefixed, see common.py):
  first byte on the connection selects the workload:
  F  file transfer : client sends 8-byte size then the raw bytes;
                     server replies with the 32-byte SHA-256 of what it got.
  R  request/resp  : each request message is echoed back as one message.
  P  periodic      : messages carry (seq, send_time); an empty message ends
                     the run and the server replies with JSON stats.
"""
import argparse
import hashlib
import json
import socket
import struct
import threading
import time

from common import HOST, TCP_PORT, recv_exact, recv_msg, send_msg

PERIODIC_HDR = struct.Struct("!Id")  # seq, sender perf_counter()


def handle(conn):
    # Disable Nagle's algorithm: without this, small writes can be held back
    # waiting for an ACK, and with delayed ACKs on the other side that adds
    # up to ~40-200 ms per small message.
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        mode = recv_exact(conn, 1)
        if mode == b"F":
            (size,) = struct.unpack("!Q", recv_exact(conn, 8))
            h = hashlib.sha256()
            remaining = size
            while remaining:
                chunk = conn.recv(min(65536, remaining))
                if not chunk:
                    break
                h.update(chunk)
                remaining -= len(chunk)
            conn.sendall(h.digest())

        elif mode == b"R":
            while True:
                msg = recv_msg(conn)
                if msg is None:
                    break
                send_msg(conn, msg)

        elif mode == b"P":
            delays, seqs = [], set()
            while True:
                msg = recv_msg(conn)
                if not msg:  # empty message = end of run (None = closed)
                    break
                seq, sent_at = PERIODIC_HDR.unpack_from(msg)
                # client and server are on the same host, so perf_counter()
                # values are comparable and give one-way delay
                delays.append(time.perf_counter() - sent_at)
                seqs.add(seq)
            if msg is not None:
                send_msg(conn, json.dumps({"received": len(seqs), "delays": delays}).encode())
    except (OSError, struct.error):
        pass
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=TCP_PORT)
    a = p.parse_args()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, a.port))
    srv.listen(16)
    print(f"[TCP] listening on {HOST}:{a.port}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
