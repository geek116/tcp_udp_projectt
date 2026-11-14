"""UDP server for the three workloads (final version).

Run: python final/udp_server.py [--port 5002]

Every datagram starts with a 1-byte type:
  S start file   : session, total_size, n_chunks        -> 'a' ack
  D file data    : session, seq, payload                 -> 'k' ack(seq)
  F finish file  : session  -> 'h' + SHA-256, only once every chunk is in
  Q request      : seq, payload                          -> 'q' echo
  M periodic msg : session, seq, send_time (no reply)
  T periodic end : session  -> 't' + JSON summary

UDP gives no delivery, ordering or duplicate guarantees, so the CLIENT
implements reliability for file transfer and request/response (sequence
numbers, ACKs, timeouts, retransmission). The server just has to be
idempotent: duplicates are acknowledged again but stored once.
"""
import argparse
import hashlib
import json
import struct
import time

from common import HOST, UDP_PORT, latency_summary, make_udp_socket, udp_recv

START = struct.Struct("!cIQI")
DATA = struct.Struct("!cII")
SESS = struct.Struct("!cI")
REQ = struct.Struct("!cI")
PER = struct.Struct("!cIId")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=UDP_PORT)
    a = p.parse_args()
    sock = make_udp_socket((HOST, a.port))
    print(f"[UDP] listening on {HOST}:{a.port}", flush=True)

    files = {}      # session -> {"n": n_chunks, "size": size, "chunks": {seq: bytes}}
    periodic = {}   # session -> {"seqs": set(), "delays": []}

    while True:
        data, addr = udp_recv(sock)
        if not data:
            continue
        kind = data[:1]

        if kind == b"D":
            _, sess, seq = DATA.unpack_from(data)
            f = files.get(sess)
            if f is not None and seq < f["n"]:
                f["chunks"].setdefault(seq, data[DATA.size:])
                sock.sendto(DATA.pack(b"k", sess, seq), addr)

        elif kind == b"Q":
            sock.sendto(b"q" + data[1:], addr)

        elif kind == b"M":
            _, sess, seq, sent_at = PER.unpack_from(data)
            s = periodic.setdefault(sess, {"seqs": set(), "delays": []})
            if seq not in s["seqs"]:
                s["seqs"].add(seq)
                s["delays"].append(time.perf_counter() - sent_at)

        elif kind == b"S":
            _, sess, size, n = START.unpack_from(data)
            if sess not in files:
                files.clear()  # only one transfer at a time; free memory
                files[sess] = {"n": n, "size": size, "chunks": {}}
            sock.sendto(SESS.pack(b"a", sess), addr)

        elif kind == b"F":
            _, sess = SESS.unpack_from(data)
            f = files.get(sess)
            if f is not None and len(f["chunks"]) == f["n"]:
                h = hashlib.sha256()
                for i in range(f["n"]):
                    h.update(f["chunks"][i])
                sock.sendto(SESS.pack(b"h", sess) + h.digest(), addr)

        elif kind == b"T":
            _, sess = SESS.unpack_from(data)
            s = periodic.get(sess, {"seqs": set(), "delays": []})
            summary = {"received": len(s["seqs"])}
            summary.update(latency_summary(s["delays"]))
            sock.sendto(SESS.pack(b"t", sess) + json.dumps(summary).encode(), addr)


if __name__ == "__main__":
    main()
