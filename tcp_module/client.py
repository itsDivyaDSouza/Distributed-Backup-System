
#!/usr/bin/env python3
"""Chunked TCP backup client with two-node placement and restart/resume support."""

import argparse
import hashlib
import json
import os
import socket
import struct
import time
import uuid

CHUNK_SIZE = 65536
MAX_MESSAGE = 1024 * 1024


def recv_exact(sock, size):

    data = bytearray()

    while len(data) < size:

        part = sock.recv(min(65536, size - len(data)))

        if not part:
            raise ConnectionError(
                "Server disconnected before response completed"
            )

        data.extend(part)

    return bytes(data)


def send_json(sock, value):

    raw = json.dumps(value).encode("utf-8")

    sock.sendall(
        struct.pack("!I", len(raw)) + raw
    )


def recv_json(sock):

    length = struct.unpack(
        "!I",
        recv_exact(sock, 4)
    )[0]

    if length <= 0 or length > MAX_MESSAGE:
        raise ValueError("Invalid server response length")

    return json.loads(
        recv_exact(sock, length).decode("utf-8")
    )


def request(server, message, payload=None):

    with socket.create_connection(
        (server["host"], server["port"]),
        timeout=5
    ) as sock:

        sock.settimeout(30)

        send_json(sock, message)

        if payload is not None and len(payload):
            sock.sendall(payload)

        response = recv_json(sock)

        if response.get("status") != "ok":
            raise RuntimeError(
                response.get("message", "Server request failed")
            )

        return response, sock


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):

    digest = hashlib.sha256()

    with open(path, "rb") as file:

        for block in iter(
            lambda: file.read(1024 * 1024),
            b""
        ):
            digest.update(block)

    return digest.hexdigest()


def get_status(server, backup_id):

    response, _ = request(
        server,
        {
            "action": "status",
            "backup_id": backup_id
        }
    )

    return {
        int(key): value
        for key, value in response.get("chunks", {}).items()
    }


def save_manifest(manifest, directory="backup_metadata"):

    os.makedirs(directory, exist_ok=True)

    path = os.path.join(
        directory,
        manifest["backup_id"] + ".json"
    )

    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=4)

    os.replace(temp_path, path)


def put_chunk(
    server,
    backup_id,
    filename,
    chunk_id,
    total_chunks,
    data,
    checksum
):

    message = {
        "action": "put",
        "backup_id": backup_id,
        "filename": filename,
        "chunk_id": chunk_id,
        "total_chunks": total_chunks,
        "chunk_size": len(data),
        "checksum": checksum
    }

    response, _ = request(
        server,
        message,
        data
    )

    return response


def get_chunk(server, backup_id, filename, chunk_id):

    with socket.create_connection(
        (server["host"], server["port"]),
        timeout=5
    ) as sock:

        sock.settimeout(30)

        send_json(sock, {
            "action": "get",
            "backup_id": backup_id,
            "filename": filename,
            "chunk_id": chunk_id
        })

        response = recv_json(sock)

        if response.get("status") != "ok":
            raise RuntimeError(
                response.get("message", "Chunk retrieval failed")
            )

        size = int(response["size"])

        data = (
            recv_exact(sock, size)
            if size
            else b""
        )

        if sha256_bytes(data) != response["checksum"]:
            raise RuntimeError(
                f"Chunk {chunk_id} failed checksum during retrieval"
            )

        return data


def main():

    parser = argparse.ArgumentParser(
        description="Distributed TCP backup client"
    )

    parser.add_argument(
        "--file",
        required=True,
        help="File to back up"
    )

    parser.add_argument(
        "--backup-id",
        default=None,
        help="Reuse this ID to resume an interrupted backup"
    )

    parser.add_argument(
        "--server1",
        default=os.environ.get(
            "BACKUP_SERVER1",
            "10.0.0.2"
        )
    )

    parser.add_argument(
        "--server2",
        default=os.environ.get(
            "BACKUP_SERVER2",
            "10.0.0.3"
        )
    )

    parser.add_argument(
        "--port",
        type=int,
        default=int(
            os.environ.get("BACKUP_PORT", "5001")
        )
    )

    parser.add_argument(
        "--port2",
        type=int,
        default=None,
        help="Optional second-server port for local testing"
    )

    parser.add_argument(
        "--output-dir",
        default="recovered_files"
    )

    args = parser.parse_args()

    file_path = os.path.abspath(
        os.path.expanduser(args.file)
    )

    if not os.path.isfile(file_path):
        parser.error(
            "Input file does not exist: " + file_path
        )

    filename = os.path.basename(file_path)

    backup_id = (
        args.backup_id
        or str(uuid.uuid4())
    )

    file_size = os.path.getsize(file_path)

    total_chunks = (
        file_size + CHUNK_SIZE - 1
    ) // CHUNK_SIZE

    whole_hash = sha256_file(file_path)

    servers = [
        {
            "id": "server_1",
            "host": args.server1,
            "port": args.port
        },
        {
            "id": "server_2",
            "host": args.server2,
            "port": args.port2 or args.port
        }
    ]

    print("Backup ID:", backup_id)
    print("File:", filename)
    print("File size:", file_size, "bytes")
    print("Chunk size:", CHUNK_SIZE, "bytes")
    print("Total chunks:", total_chunks)
    print("File SHA-256:", whole_hash)

    print(
        "Backup servers:",
        f"{servers[0]['host']} ({servers[0]['id']}),",
        f"{servers[1]['host']} ({servers[1]['id']})"
    )

    manifest_dir = os.environ.get(
        "BACKUP_METADATA_DIR",
        "backup_metadata"
    )

    manifest_path = os.path.join(
        manifest_dir,
        backup_id + ".json"
    )

    if os.path.isfile(manifest_path):

        with open(
            manifest_path,
            "r",
            encoding="utf-8"
        ) as file:

            manifest = json.load(file)

        if (
            manifest.get("filename") != filename
            or int(manifest.get("total_chunks", -1)) != total_chunks
            or manifest.get("file_sha256") != whole_hash
        ):

            raise SystemExit(
                "ERROR: This backup ID already belongs "
                "to a different file/version."
            )

    else:

        manifest = {
            "backup_id": backup_id,
            "filename": filename,
            "total_chunks": total_chunks,
            "file_sha256": whole_hash,
            "chunks": {},
            "status": "in_progress"
        }

        save_manifest(
            manifest,
            manifest_dir
        )

    started = time.perf_counter()

    statuses = {}
    available = []

    # Discover which servers are reachable and which chunks they already have.

    for server in servers:

        try:

            statuses[server["id"]] = get_status(
                server,
                backup_id
            )

            available.append(server)

            print(
                f"{server['id']} reachable; "
                f"existing chunks: "
                f"{len(statuses[server['id']])}"
            )

        except (
            OSError,
            RuntimeError,
            ValueError
        ) as exc:

            print(
                f"WARNING: {server['id']} "
                f"({server['host']}) unavailable: {exc}"
            )

    if not available:
        raise SystemExit(
            "ERROR: No backup server is reachable."
        )

    # Send chunks in alternating order.
    # Existing valid chunks are skipped when resuming.

    with open(file_path, "rb") as source:

        for chunk_id in range(total_chunks):

            data = source.read(CHUNK_SIZE)
            checksum = sha256_bytes(data)

            stored = False

            for server in available:

                entry = statuses[
                    server["id"]
                ].get(chunk_id)

                if (
                    entry
                    and entry.get("checksum") == checksum
                    and int(entry.get("size", -1)) == len(data)
                ):

                    print(
                        f"Chunk {chunk_id}: already present "
                        f"on {server['id']} - skipped"
                    )

                    manifest["chunks"][str(chunk_id)] = {
                        "chunk_id": chunk_id,
                        "chunk_size": len(data),
                        "checksum": checksum,
                        "server_id": server["id"],
                        "status": "stored"
                    }

                    save_manifest(
                        manifest,
                        manifest_dir
                    )

                    stored = True
                    break

            if stored:
                continue

            preferred = servers[
                chunk_id % len(servers)
            ]

            order = (
                [preferred]
                + [
                    server
                    for server in available
                    if server["id"] != preferred["id"]
                ]
            )

            order = [
                server
                for server in order
                if server in available
            ]

            last_error = None

            for server in order:

                try:

                    ack = put_chunk(
                        server,
                        backup_id,
                        filename,
                        chunk_id,
                        total_chunks,
                        data,
                        checksum
                    )

                    statuses[
                        server["id"]
                    ][chunk_id] = {
                        "checksum": checksum,
                        "size": len(data)
                    }

                    manifest["chunks"][str(chunk_id)] = {
                        "chunk_id": chunk_id,
                        "chunk_size": len(data),
                        "checksum": checksum,
                        "server_id": ack.get(
                            "server_id",
                            server["id"]
                        ),
                        "status": "stored"
                    }

                    save_manifest(
                        manifest,
                        manifest_dir
                    )

                    print(
                        f"Chunk {chunk_id}: stored and "
                        f"verified on {server['id']}"
                    )

                    stored = True
                    break

                except (
                    OSError,
                    RuntimeError,
                    ValueError
                ) as exc:

                    last_error = exc

                    print(
                        f"WARNING: Could not store chunk "
                        f"{chunk_id} on {server['id']}: {exc}"
                    )

            if not stored:

                raise SystemExit(
                    f"ERROR: Chunk {chunk_id} could not be stored: "
                    f"{last_error}. Re-run with --backup-id "
                    f"{backup_id} to resume."
                )

    transfer_seconds = (
        time.perf_counter() - started
    )

    throughput = (
        (file_size / (1024 * 1024)) / transfer_seconds
        if transfer_seconds > 0
        else 0.0
    )

    print(
        f"All {total_chunks} chunks are stored."
    )

    print(
        f"Transfer elapsed time: "
        f"{transfer_seconds:.4f} seconds"
    )

    print(
        f"Effective upload throughput: "
        f"{throughput:.3f} MiB/s"
    )

    # Refresh server inventories before reconstructing the file.

    for server in available:

        try:

            statuses[server["id"]] = get_status(
                server,
                backup_id
            )

        except (
            OSError,
            RuntimeError,
            ValueError
        ) as exc:

            print(
                f"WARNING: status refresh failed "
                f"for {server['id']}: {exc}"
            )

    os.makedirs(
        args.output_dir,
        exist_ok=True
    )

    output_path = os.path.join(
        args.output_dir,
        "reconstructed_" + filename
    )

    temp_path = output_path + ".tmp"

    recovery_started = time.perf_counter()

    final_hash = hashlib.sha256()

    try:

        with open(temp_path, "wb") as output:

            for chunk_id in range(total_chunks):

                data = None

                expected_size = min(
                    CHUNK_SIZE,
                    file_size - chunk_id * CHUNK_SIZE
                )

                # Retrieve the chunk from whichever server has a valid copy.

                for server in available:

                    entry = statuses[
                        server["id"]
                    ].get(chunk_id)

                    if (
                        not entry
                        or int(entry.get("size", -1)) != expected_size
                    ):
                        continue

                    try:

                        candidate = get_chunk(
                            server,
                            backup_id,
                            filename,
                            chunk_id
                        )

                        if (
                            sha256_bytes(candidate)
                            == entry["checksum"]
                        ):

                            data = candidate
                            break

                    except (
                        OSError,
                        RuntimeError,
                        ValueError
                    ) as exc:

                        print(
                            f"WARNING: retrieval from "
                            f"{server['id']} for chunk "
                            f"{chunk_id} failed: {exc}"
                        )

                if data is None:

                    raise RuntimeError(
                        f"Chunk {chunk_id} is missing or "
                        "corrupt on all available servers"
                    )

                output.write(data)
                final_hash.update(data)

                manifest["chunks"][str(chunk_id)]["status"] = (
                    "verified"
                )

        actual_hash = final_hash.hexdigest()

        if actual_hash != whole_hash:
            raise RuntimeError(
                "Whole-file SHA-256 mismatch"
            )

        os.replace(
            temp_path,
            output_path
        )

    except Exception:

        if os.path.exists(temp_path):
            os.remove(temp_path)

        raise

    recovery_seconds = (
        time.perf_counter() - recovery_started
    )

    manifest["status"] = "completed"

    save_manifest(
        manifest,
        manifest_dir
    )

    print("Reconstructed file:", output_path)
    print("Reconstructed SHA-256:", actual_hash)
    print("Whole-file SHA-256: VERIFIED")

    print(
        f"Reconstruction/retrieval time: "
        f"{recovery_seconds:.4f} seconds"
    )

    print("Backup manifest:", manifest_path)
    print("Backup transfer completed successfully.")

    print(
        "RESUME: If interrupted, rerun with the same "
        "--backup-id:",
        backup_id
    )


if __name__ == "__main__":
    main()
