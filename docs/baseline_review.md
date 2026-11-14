# Line-by-line review of the AI baseline

For every function: which call actually puts bytes on the network, and which call takes them off. "Kernel" means the operating system's network stack. Python's `send`/`sendto` hand bytes to the kernel, and the kernel puts them on the wire (here, the loopback interface).

## baseline/tcp_server.py

| Function | Takes bytes off the network | Puts bytes on the network | Notes |
|---|---|---|---|
| `main()` | `server.accept()` completes the 3-way handshake (SYN, SYN-ACK, ACK) done by the kernel | (kernel sends SYN-ACK) | `bind()` and `listen()` send nothing |
| `handle_client()` mode F | `conn.recv(4096)` | none from the app (kernel sends ACKs) | Loop ends when `recv` returns `b""`, i.e. the client sent FIN |
| `handle_client()` mode R | `conn.recv(4096)` | `conn.sendall(data)` | **Bug:** assumes one `recv` = one request. TCP is a byte stream, so a recv can hold part of a message or several messages |
| `handle_client()` mode P | `conn.recv(4096)` | none | **Bug:** `count` counts `recv()` calls, not messages. If messages coalesce into one segment, the count is too low |
| `conn.close()` | | sends FIN | |

## baseline/tcp_client.py

| Function | Puts bytes on the network | Takes bytes off | Notes |
|---|---|---|---|
| `file_transfer()` | `sock.connect()` (SYN), `sock.sendall(b"F")`, `sock.sendall(data)`, `sock.close()` (FIN) | none | **Bug:** the timer stops after `sendall()` returns. `sendall()` returns once bytes are copied into the local kernel send buffer, not when the server has them. Measured ~34,500 Mbit/s for 1 MB even with 100 ms RTT, which is impossible |
| `request_response()` | `sock.sendall(message)` | `sock.recv(4096)` | Same stream-boundary assumption; no `TCP_NODELAY`, so Nagle's algorithm can delay small writes |
| `periodic()` | `sock.sendall(message)` | none | `time.sleep(interval)` after each send drifts: only ~2,945 of 3,000 messages are sent in 30 s |

## baseline/udp_server.py

| Branch | Takes off | Puts on | Notes |
|---|---|---|---|
| all | `sock.recvfrom(65535)` | | No handling of Windows `ConnectionResetError` (WSAECONNRESET) |
| `F` chunk | | none | Writes chunks in **arrival order**, with no sequence numbers. Loss, reordering or duplication silently corrupt the file |
| `E` end | | `sock.sendto(b"OK", addr)` | If `E` or `OK` is lost, the client waits forever |
| `R` request | | `sock.sendto(data, addr)` | Echo |
| `P` periodic | | none | Counts messages, but prints only every 100th, so the exact count is not reported |

## baseline/udp_client.py

| Function | Puts on | Takes off | Notes |
|---|---|---|---|
| `file_transfer()` | `sock.sendto(b"F"+chunk)` in a tight loop, then `sendto(b"E")` | `sock.recvfrom()` (no timeout) | **No flow control:** sends as fast as the CPU allows and overflows the receiver's socket buffer. Lost 1–11% of the 1 MB file **on clean localhost** (SHA-256 correct in only 1 of 10 clean runs). No retransmission. Blocks forever if `E`/`OK` is lost |
| `request_response()` | `sock.sendto(message)` | `sock.recvfrom()` with 1 s timeout | **No sequence numbers:** a late reply to request *n* is taken as the reply to request *n+1*, so the latency is wrong. Fixed 1 s timeout is 10× the 100 ms RTT, so each loss costs 1 s |
| `periodic()` | `sock.sendto(message)` | none | No sequence numbers or timestamps, so loss and delay cannot be measured |

## baseline/timing.py

Calls the client functions and prints results. It sends nothing itself. It cannot report loss, delivery rate, one-way delay or file integrity (no SHA-256 check).
