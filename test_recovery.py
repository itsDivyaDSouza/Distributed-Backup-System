
import os
import shutil
import hashlib

from tcp_module.storage_manager import (
    create_backup,
    register_chunk,
    check_chunks
)

backup_id = "backup_recovery_test"
filename = "sample.txt"

shutil.rmtree("test_storage", ignore_errors=True)
os.makedirs("test_storage/server_1", exist_ok=True)
os.makedirs("test_storage/server_2", exist_ok=True)
os.makedirs("test_storage/server_3", exist_ok=True)

server_roots = {
    "server_1": "test_storage/server_1",
    "server_2": "test_storage/server_2",
    "server_3": "test_storage/server_3"
}

chunks = [
    b"First chunk of the file.",
    b"Second chunk of the file.",
    b"Third chunk of the file."
]

original_file = b"".join(chunks)
file_hash = hashlib.sha256(original_file).hexdigest()

create_backup(
    backup_id,
    filename,
    len(chunks),
    file_hash
)

for i, data in enumerate(chunks):
    server_id = "server_" + str(i + 1)
    chunk_hash = hashlib.sha256(data).hexdigest()

    metadata = {
        "backup_id": backup_id,
        "filename": filename,
        "total_chunks": len(chunks),
        "chunk_id": i,
        "chunk_size": len(data),
        "checksum": chunk_hash,
        "server_id": server_id
    }

    register_chunk(backup_id, metadata)

    folder = os.path.join(server_roots[server_id], backup_id)
    os.makedirs(folder, exist_ok=True)

    path = os.path.join(
        folder,
        filename + ".chunk_" + str(i)
    )

    with open(path, "wb") as file:
        file.write(data)

# Delete chunk 1 to simulate a missing chunk
os.remove(
    os.path.join(
        server_roots["server_2"],
        backup_id,
        filename + ".chunk_1"
    )
)

# Modify chunk 2 to simulate corruption
corrupt_path = os.path.join(
    server_roots["server_3"],
    backup_id,
    filename + ".chunk_2"
)

with open(corrupt_path, "wb") as file:
    file.write(b"Corrupted data!")

missing, corrupted = check_chunks(
    backup_id,
    server_roots
)

print("Missing chunks:", missing)
print("Corrupted chunks:", corrupted)

assert missing == [1]
assert corrupted == [2]

print("Recovery detection test passed!")
