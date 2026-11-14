"""Simple UDP client for the three workloads."""
import socket
import time

HOST = "127.0.0.1"
PORT = 5002
CHUNK_SIZE = 1024
BUFFER_SIZE = 65535


def file_transfer(filename, host=HOST, port=PORT):
    """Send a file in chunks. Returns (bytes_sent, seconds)."""
    with open(filename, "rb") as f:
        data = f.read()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start = time.perf_counter()
    for i in range(0, len(data), CHUNK_SIZE):
        sock.sendto(b"F" + data[i:i + CHUNK_SIZE], (host, port))
    sock.sendto(b"E", (host, port))
    sock.recvfrom(BUFFER_SIZE)  # wait for OK
    elapsed = time.perf_counter() - start
    sock.close()
    return len(data), elapsed


def request_response(count=1000, size=64, host=HOST, port=PORT):
    """Send `count` requests and wait for each echo. Returns list of RTTs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    message = b"R" + b"x" * (size - 1)
    latencies = []
    lost = 0
    for _ in range(count):
        start = time.perf_counter()
        sock.sendto(message, (host, port))
        try:
            sock.recvfrom(BUFFER_SIZE)
            latencies.append(time.perf_counter() - start)
        except socket.timeout:
            lost += 1
    sock.close()
    if lost:
        print(f"{lost} requests timed out")
    return latencies


def periodic(rate=100, duration=30, size=64, host=HOST, port=PORT):
    """Send small messages at `rate` per second for `duration` seconds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    message = b"P" + b"x" * (size - 1)
    interval = 1.0 / rate
    sent = 0
    end_time = time.perf_counter() + duration
    while time.perf_counter() < end_time:
        sock.sendto(message, (host, port))
        sent += 1
        time.sleep(interval)
    sock.close()
    return sent


if __name__ == "__main__":
    n, t = file_transfer("test.bin")
    print(f"Sent {n} bytes in {t:.3f}s")
