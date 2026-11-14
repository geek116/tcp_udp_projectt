"""Simple UDP server supporting three workloads.

Run: python udp_server.py [port]

Each datagram starts with one byte that says what it is:
  F = file chunk, E = end of file
  R = request (echoed back)
  P = periodic message (counted)
"""
import socket
import sys

HOST = "127.0.0.1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5002
BUFFER_SIZE = 65535


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    print(f"[UDP] Server listening on {HOST}:{PORT}")

    file_handle = None
    file_bytes = 0
    periodic_count = 0

    while True:
        data, addr = sock.recvfrom(BUFFER_SIZE)
        kind, payload = data[:1], data[1:]

        if kind == b"F":
            if file_handle is None:
                file_handle = open("received_udp.bin", "wb")
                file_bytes = 0
            file_handle.write(payload)
            file_bytes += len(payload)

        elif kind == b"E":
            if file_handle is not None:
                file_handle.close()
                file_handle = None
            print(f"[UDP] File received: {file_bytes} bytes")
            sock.sendto(b"OK", addr)

        elif kind == b"R":
            sock.sendto(data, addr)

        elif kind == b"P":
            periodic_count += 1
            if periodic_count % 100 == 0:
                print(f"[UDP] Periodic messages received: {periodic_count}")


if __name__ == "__main__":
    main()
