
import os
import json
import hashlib

MANIFEST_DIR = "backup_metadata"


def get_manifest_path(backup_id):
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    return os.path.join(MANIFEST_DIR, backup_id + ".json")


def save_manifest(backup_id, manifest):
    path = get_manifest_path(backup_id)
    temp_path = path + ".tmp"

    with open(temp_path, "w") as file:
        json.dump(manifest, file, indent=4)

    os.replace(temp_path, path)


def load_manifest(backup_id):
    path = get_manifest_path(backup_id)

    if not os.path.isfile(path):
        return None

    with open(path, "r") as file:
        return json.load(file)


def create_backup(backup_id, filename, total_chunks, file_sha256):
    manifest = {
        "backup_id": backup_id,
        "filename": filename,
        "total_chunks": total_chunks,
        "file_sha256": file_sha256,
        "chunks": {}
    }

    save_manifest(backup_id, manifest)
    print("Backup manifest created:", backup_id)

    return manifest


def register_chunk(backup_id, metadata):
    manifest = load_manifest(backup_id)

    if manifest is None:
        raise ValueError("Backup manifest not found")

    if metadata["backup_id"] != backup_id:
        raise ValueError("Backup ID mismatch")

    if metadata["filename"] != manifest["filename"]:
        raise ValueError("Filename mismatch")

    if int(metadata["total_chunks"]) != manifest["total_chunks"]:
        raise ValueError("Total chunks mismatch")

    chunk_id = int(metadata["chunk_id"])

    if chunk_id < 0 or chunk_id >= manifest["total_chunks"]:
        raise ValueError("Invalid chunk ID")

    manifest["chunks"][str(chunk_id)] = {
        "chunk_id": chunk_id,
        "chunk_size": int(metadata["chunk_size"]),
        "checksum": metadata["checksum"],
        "server_id": metadata["server_id"],
        "status": "stored"
    }

    save_manifest(backup_id, manifest)
    print("Registered chunk:", chunk_id)


def sha256_file(path):
    digest = hashlib.sha256()

    with open(path, "rb") as file:
        while True:
            data = file.read(65536)

            if not data:
                break

            digest.update(data)

    return digest.hexdigest()

def get_chunk_path(server_root, backup_id, filename, chunk_id):
    return os.path.join(
        server_root,
        backup_id,
        filename + ".chunk_" + str(chunk_id)
    )


def check_chunks(backup_id, server_roots):
    manifest = load_manifest(backup_id)

    if manifest is None:
        raise ValueError("Backup manifest not found")

    missing = []
    corrupted = []

    for chunk_id in range(manifest["total_chunks"]):
        key = str(chunk_id)
        entry = manifest["chunks"].get(key)

        if entry is None:
            missing.append(chunk_id)
            continue

        server_id = entry["server_id"]
        root = server_roots.get(server_id)

        if root is None:
            missing.append(chunk_id)
            continue

        path = get_chunk_path(
            root,
            backup_id,
            manifest["filename"],
            chunk_id
        )

        if not os.path.isfile(path):
            missing.append(chunk_id)
            continue

        if os.path.getsize(path) != entry["chunk_size"]:
            corrupted.append(chunk_id)
            continue

        actual_hash = sha256_file(path)

        if actual_hash != entry["checksum"]:
            corrupted.append(chunk_id)
            continue

        entry["status"] = "verified"

    for chunk_id in missing:
        key = str(chunk_id)
        if key in manifest["chunks"]:
            manifest["chunks"][key]["status"] = "missing"

    for chunk_id in corrupted:
        manifest["chunks"][str(chunk_id)]["status"] = "corrupted"

    save_manifest(backup_id, manifest)

    return missing, corrupted

def reconstruct_file(backup_id, server_roots, output_dir="recovered_files"):
    manifest = load_manifest(backup_id)

    if manifest is None:
        raise ValueError("Backup manifest not found")

    missing, corrupted = check_chunks(backup_id, server_roots)

    if missing or corrupted:
        print("Missing chunks:", missing)
        print("Corrupted chunks:", corrupted)
        print("Cannot reconstruct: recovery is required.")
        return None

    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(
        output_dir,
        "reconstructed_" + manifest["filename"]
    )

    temp_path = output_path + ".tmp"

    try:
        with open(temp_path, "wb") as output:
            for chunk_id in range(manifest["total_chunks"]):
                entry = manifest["chunks"][str(chunk_id)]

                chunk_path = get_chunk_path(
                    server_roots[entry["server_id"]],
                    backup_id,
                    manifest["filename"],
                    chunk_id
                )

                with open(chunk_path, "rb") as chunk:
                    while True:
                        data = chunk.read(65536)

                        if not data:
                            break

                        output.write(data)

        actual_hash = sha256_file(temp_path)

        if actual_hash != manifest["file_sha256"]:
            raise ValueError(
                "Reconstructed file checksum mismatch"
            )

        os.replace(temp_path, output_path)

    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    print("Reconstructed file:", output_path)
    print("SHA-256:", actual_hash)
    print("Whole-file verification successful!")

    return output_path

def repair_chunk(backup_id, chunk_id, data, server_roots):
    manifest = load_manifest(backup_id)

    if manifest is None:
        raise ValueError("Backup manifest not found")

    entry = manifest["chunks"].get(str(chunk_id))

    if entry is None:
        raise ValueError("Chunk is not registered in the manifest")

    if len(data) != entry["chunk_size"]:
        raise ValueError("Recovered chunk size mismatch")

    actual_hash = hashlib.sha256(data).hexdigest()

    if actual_hash != entry["checksum"]:
        raise ValueError("Recovered chunk checksum mismatch")

    server_id = entry["server_id"]
    root = server_roots.get(server_id)

    if root is None:
        raise ValueError("Target storage server is unavailable")

    backup_dir = os.path.join(root, backup_id)
    os.makedirs(backup_dir, exist_ok=True)

    path = get_chunk_path(
        root,
        backup_id,
        manifest["filename"],
        chunk_id
    )

    temp_path = path + ".tmp"

    try:
        with open(temp_path, "wb") as file:
            file.write(data)

        os.replace(temp_path, path)

    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    entry["status"] = "verified"
    save_manifest(backup_id, manifest)

    print("Chunk recovered and verified:", chunk_id)
