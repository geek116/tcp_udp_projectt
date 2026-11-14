"""User-space network impairment proxy (replacement for `tc netem`).

Sits between a client and a server and adds delay (and, for UDP, random loss)
to traffic in BOTH directions, like netem on the loopback interface.

UDP:  python tests/proxy.py udp --listen 6002 --target 5002 --loss 0.05 --delay 0.05
TCP:  python tests/proxy.py tcp --listen 6001 --target 5001 --delay 0.05

Why no TCP loss: the proxy terminates the TCP connection on each side, so the
client's kernel and the proxy's kernel already deliver every byte reliably
before the proxy sees it. Dropping bytes here would corrupt the stream rather
than make TCP retransmit. Real TCP loss needs netem (or another kernel-level
tool), which is not available on this machine. See docs/environment.md.

Also note: because the proxy ACKs on behalf of the server, TCP's own
congestion/flow control sees a ~0 ms RTT to the proxy. The delay is applied to
the forwarded bytes, so latency is realistic but bulk-transfer throughput under
delay is NOT what real TCP over a 100 ms RTT path would achieve.
"""
import argparse
import heapq
import random
import socket
import threading
import time
from collections import deque

BUF = 65535
SOCK_BUF = 4 * 1024 * 1024


class DelayLine:
    """Delivers callables at a scheduled time on a single worker thread."""

    def __init__(self):
        self._heap = []
        self._counter = 0
        self._cv = threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()

    def schedule(self, due, func, *args):
        with self._cv:
            heapq.heappush(self._heap, (due, self._counter, func, args))
            self._counter += 1
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while not self._heap:
                    self._cv.wait()
                due, _, func, args = self._heap[0]
                wait = due - time.perf_counter()
                if wait > 0:
                    self._cv.wait(wait)
                    continue
                heapq.heappop(self._heap)
            try:
                func(*args)
            except OSError:
                pass


def recvfrom_safe(sock):
    """recvfrom that ignores Windows' WSAECONNRESET (ICMP port unreachable)."""
    while True:
        try:
            return sock.recvfrom(BUF)
        except ConnectionResetError:
            continue


class UDPProxy:
    def __init__(self, listen_port, target_port, loss, delay, jitter, seed, host="127.0.0.1"):
        self.target = (host, target_port)
        self.loss, self.delay, self.jitter = loss, delay, jitter
        self.rng = random.Random(seed)
        self.rng_lock = threading.Lock()
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for s in (self.front, self.back):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCK_BUF)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCK_BUF)
        self.front.bind((host, listen_port))
        self.back.bind((host, 0))
        self.client_addr = None
        self.line = DelayLine()
        self.stats = {"c2s": 0, "c2s_dropped": 0, "s2c": 0, "s2c_dropped": 0}

    def _decide(self):
        with self.rng_lock:
            drop = self.rng.random() < self.loss
            d = self.delay + (self.rng.uniform(-self.jitter, self.jitter) if self.jitter else 0)
        return drop, max(0.0, d)

    def _client_to_server(self):
        while True:
            data, addr = recvfrom_safe(self.front)
            self.client_addr = addr
            self.stats["c2s"] += 1
            drop, d = self._decide()
            if drop:
                self.stats["c2s_dropped"] += 1
                continue
            self.line.schedule(time.perf_counter() + d, self.back.sendto, data, self.target)

    def _server_to_client(self):
        while True:
            data, _ = recvfrom_safe(self.back)
            self.stats["s2c"] += 1
            drop, d = self._decide()
            if drop or self.client_addr is None:
                self.stats["s2c_dropped"] += 1
                continue
            self.line.schedule(time.perf_counter() + d, self.front.sendto, data, self.client_addr)

    def serve_forever(self):
        threading.Thread(target=self._server_to_client, daemon=True).start()
        self._client_to_server()


class TCPProxy:
    def __init__(self, listen_port, target_port, delay, jitter, seed, host="127.0.0.1"):
        self.target = (host, target_port)
        self.delay, self.jitter = delay, jitter
        self.rng = random.Random(seed)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, listen_port))
        self.listener.listen(16)

    def _pump(self, src, dst):
        """Read from src, forward to dst after `delay`, preserving byte order."""
        q = deque()
        cv = threading.Condition()

        def reader():
            while True:
                try:
                    data = src.recv(BUF)
                except OSError:
                    data = b""
                d = self.delay + (self.rng.uniform(0, self.jitter) if self.jitter else 0)
                with cv:
                    # keep due times non-decreasing so bytes stay in order
                    due = time.perf_counter() + d
                    if q and q[-1][0] > due:
                        due = q[-1][0]
                    q.append((due, data))
                    cv.notify()
                if not data:
                    return

        def writer():
            while True:
                with cv:
                    while not q:
                        cv.wait()
                    due, data = q[0]
                    wait = due - time.perf_counter()
                    if wait > 0:
                        cv.wait(wait)
                        continue
                    q.popleft()
                try:
                    if not data:
                        dst.shutdown(socket.SHUT_WR)
                        return
                    dst.sendall(data)
                except OSError:
                    return

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=writer, daemon=True).start()

    def serve_forever(self):
        while True:
            client, _ = self.listener.accept()
            try:
                upstream = socket.create_connection(self.target)
            except OSError:
                client.close()
                continue
            for s in (client, upstream):
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._pump(client, upstream)
            self._pump(upstream, client)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("proto", choices=["udp", "tcp"])
    p.add_argument("--listen", type=int, required=True)
    p.add_argument("--target", type=int, required=True)
    p.add_argument("--loss", type=float, default=0.0, help="UDP drop probability per datagram per direction")
    p.add_argument("--delay", type=float, default=0.0, help="one-way delay in seconds (each direction)")
    p.add_argument("--jitter", type=float, default=0.0, help="+/- jitter in seconds")
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args()
    if a.proto == "udp":
        proxy = UDPProxy(a.listen, a.target, a.loss, a.delay, a.jitter, a.seed)
    else:
        if a.loss:
            print("WARNING: --loss is ignored for TCP (see module docstring)")
        proxy = TCPProxy(a.listen, a.target, a.delay, a.jitter, a.seed)
    print(f"[proxy] {a.proto} :{a.listen} -> :{a.target} loss={a.loss} delay={a.delay}s", flush=True)
    try:
        proxy.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
