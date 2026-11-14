"""Simple TCP client for the three workloads."""
import socket
import time

HOST = "127.0.0.1"
PORT = 5001
BUFFER_SIZE = 4096


def file_transfer(filename, host=HOST, port=PORT):
    """Send a file. Returns (bytes_sent, seconds)."""
    with open(filename, "rb") as f:
        data = f.read()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    start = time.perf_counter()
    sock.sendall(b"F")
    sock.sendall(data)
    sock.close()
    elapsed = time.perf_counter() - start
    return len(data), elapsed


def request_response(count=1000, size=64, host=HOST, port=PORT):
    """Send `count` small requests and wait for each echo. Returns list of RTTs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.sendall(b"R")
    message = b"x" * size
    latencies = []
    for _ in range(count):
        start = time.perf_counter()
        sock.sendall(message)
        sock.recv(BUFFER_SIZE)
        latencies.append(time.perf_counter() - start)
    sock.close()
    return latencies


def periodic(rate=100, duration=30, size=64, host=HOST, port=PORT):
    """Send small messages at `rate` per second for `duration` seconds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.sendall(b"P")
    message = b"x" * size
    interval = 1.0 / rate
    sent = 0
    end_time = time.perf_counter() + duration
    while time.perf_counter() < end_time:
        sock.sendall(message)
        sent += 1
        time.sleep(interval)
    sock.close()
    return sent


if __name__ == "__main__":
    n, t = file_transfer("test.bin")
    print(f"Sent {n} bytes in {t:.3f}s")
