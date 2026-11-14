"""Simple TCP server supporting three workloads.

Run: python tcp_server.py [port]

The first byte the client sends selects the workload:
  F = file transfer (client sends the file, then closes)
  R = request/response (server echoes each request)
  P = periodic messages (server counts messages)
"""
import socket
import sys

HOST = "127.0.0.1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5001
BUFFER_SIZE = 4096


def handle_client(conn, addr):
    mode = conn.recv(1)

    if mode == b"F":
        total = 0
        with open("received_tcp.bin", "wb") as f:
            while True:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                f.write(data)
                total += len(data)
        print(f"[TCP] File received from {addr}: {total} bytes")

    elif mode == b"R":
        count = 0
        while True:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                break
            conn.sendall(data)
            count += 1
        print(f"[TCP] Handled {count} requests from {addr}")

    elif mode == b"P":
        count = 0
        while True:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                break
            count += 1
        print(f"[TCP] Received {count} periodic messages from {addr}")

    conn.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"[TCP] Server listening on {HOST}:{PORT}")
    while True:
        conn, addr = server.accept()
        handle_client(conn, addr)


if __name__ == "__main__":
    main()
