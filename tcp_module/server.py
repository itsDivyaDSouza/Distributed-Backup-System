
#!/usr/bin/env python3
"""One TCP backup storage node. Run one instance on each Mininet server host."""

import argparse
import hashlib
import json
import os
import re
import socket
import struct
import threading
import time

CHUNK_SIZE = 65536
MAX_MESSAGE = 1024 * 1024
BUFFER_SIZE = 65536


def recv_exact(conn, size):
    data = bytearray()

    while len(data) < size:
        part = conn.recv(min(BUFFER_SIZE, size - len(data)))

        if not part:
            raise ConnectionError(
                "Connection closed before message was complete"
            )

        data.extend(part)

    return bytes(data)


def recv_json(conn):
    length = struct.unpack("!I", recv_exact(conn, 4))[0]

    if length <= 0 or length > MAX_MESSAGE:
        raise ValueError("Invalid metadata length")

    return json.loads(
        recv_exact(conn, length).decode("utf-8")
    )


def send_json(conn, value):
    raw = json.dumps(value).encode("utf-8")
    conn.sendall(struct.pack("!I", len(raw)) + raw)


def safe_component(value, field):
    value = str(value)

    if (
        not value
        or value in (".", "..")
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", value)
    ):
        raise ValueError("Invalid " + field)

    return value


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


class BackupServer:

    def __init__(self, host, port, server_id, storage_dir):
        self.host = host
        self.port = port
        self.server_id = server_id
        self.storage_dir = os.path.abspath(storage_dir)

        os.makedirs(self.storage_dir, exist_ok=True)

    def backup_dir(self, backup_id):
        backup_id = safe_component(backup_id, "backup_id")

        return os.path.join(
            self.storage_dir,
            backup_id
        )

    def chunk_path(self, backup_id, filename, chunk_id):
        filename = safe_component(filename, "filename")
        chunk_id = int(chunk_id)

        if chunk_id < 0:
            raise ValueError("Invalid chunk_id")

        return os.path.join(
            self.backup_dir(backup_id),
            f"{filename}.chunk_{chunk_id}"
        )

    def status(self, request):
        backup_id = safe_component(
            request["backup_id"],
            "backup_id"
        )

        folder = self.backup_dir(backup_id)
        chunks = {}

        if os.path.isdir(folder):

            for name in os.listdir(folder):

                match = re.fullmatch(
                    r"(.+)\.chunk_(\d+)",
                    name
                )

                if not match:
                    continue

                path = os.path.join(folder, name)

                if os.path.isfile(path):

                    digest = hashlib.sha256()
                    size = 0

                    with open(path, "rb") as file:

                        while True:
                            block = file.read(BUFFER_SIZE)

                            if not block:
                                break

                            size += len(block)
                            digest.update(block)

                    chunks[int(match.group(2))] = {
                        "checksum": digest.hexdigest(),
                        "size": size
                    }

        return {
            "status": "ok",
            "server_id": self.server_id,
            "chunks": chunks
        }

    def handle(self, conn, address):

        started = time.perf_counter()

        try:
            request = recv_json(conn)
            action = request.get("action")

            if action == "status":

                send_json(conn, self.status(request))

            elif action == "put":

                backup_id = safe_component(
                    request["backup_id"],
                    "backup_id"
                )

                filename = safe_component(
                    request["filename"],
                    "filename"
                )

                chunk_id = int(request["chunk_id"])
                total_chunks = int(request["total_chunks"])
                chunk_size = int(request["chunk_size"])
                expected = str(request["checksum"])

                if (
                    total_chunks < 1
                    or total_chunks > 1000000
                    or not 0 <= chunk_id < total_chunks
                ):
                    raise ValueError("Invalid chunk index/count")

                if not 0 <= chunk_size <= CHUNK_SIZE:
                    raise ValueError("Invalid chunk size")

                if not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise ValueError("Invalid SHA-256 checksum")

                data = (
                    recv_exact(conn, chunk_size)
                    if chunk_size
                    else b""
                )

                actual = sha256_bytes(data)

                if actual != expected:

                    send_json(conn, {
                        "status": "error",
                        "message": "Chunk checksum mismatch"
                    })

                else:

                    folder = self.backup_dir(backup_id)
                    os.makedirs(folder, exist_ok=True)

                    path = self.chunk_path(
                        backup_id,
                        filename,
                        chunk_id
                    )

                    temp = path + ".tmp"

                    with open(temp, "wb") as file:
                        file.write(data)

                    os.replace(temp, path)

                    print(
                        f"[{self.server_id}] Stored chunk "
                        f"{chunk_id}/{total_chunks - 1}: "
                        f"{filename} ({len(data)} bytes)",
                        flush=True
                    )

                    send_json(conn, {
                        "status": "ok",
                        "server_id": self.server_id,
                        "chunk_id": chunk_id,
                        "checksum": actual
                    })

            elif action == "get":

                path = self.chunk_path(
                    request["backup_id"],
                    request["filename"],
                    request["chunk_id"]
                )

                if not os.path.isfile(path):

                    send_json(conn, {
                        "status": "error",
                        "message": "Chunk not found"
                    })

                else:

                    with open(path, "rb") as file:
                        data = file.read()

                    send_json(conn, {
                        "status": "ok",
                        "size": len(data),
                        "checksum": sha256_bytes(data)
                    })

                    if data:
                        conn.sendall(data)

            else:

                send_json(conn, {
                    "status": "error",
                    "message": "Unknown action"
                })

        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            struct.error,
            ConnectionError
        ) as exc:

            try:
                send_json(conn, {
                    "status": "error",
                    "message": str(exc)
                })
            except OSError:
                pass

            print(
                f"[{self.server_id}] Request error from "
                f"{address}: {exc}",
                flush=True
            )

        finally:

            conn.close()

            elapsed = time.perf_counter() - started

            print(
                f"[{self.server_id}] Request completed "
                f"in {elapsed:.4f}s",
                flush=True
            )

    def serve_forever(self):

        with socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        ) as sock:

            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1
            )

            sock.bind((self.host, self.port))
            sock.listen(64)

            print(
                f"[{self.server_id}] Listening on "
                f"{self.host}:{self.port}; "
                f"storage={self.storage_dir}",
                flush=True
            )

            while True:

                conn, address = sock.accept()

                threading.Thread(
                    target=self.handle,
                    args=(conn, address),
                    daemon=True
                ).start()


def main():

    parser = argparse.ArgumentParser(
        description="Distributed backup TCP storage server"
    )

    parser.add_argument(
        "--host",
        default=os.environ.get("BACKUP_HOST", "0.0.0.0")
    )

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BACKUP_PORT", "5001"))
    )

    parser.add_argument(
        "--server-id",
        default=os.environ.get("SERVER_ID", "server_1")
    )

    parser.add_argument(
        "--storage",
        default=os.environ.get(
            "BACKUP_STORAGE",
            "received_chunks"
        )
    )

    args = parser.parse_args()

    BackupServer(
        args.host,
        args.port,
        args.server_id,
        args.storage
    ).serve_forever()


if __name__ == "__main__":
    main()
