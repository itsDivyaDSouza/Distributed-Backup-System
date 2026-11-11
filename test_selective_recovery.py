
import os
import shutil
import hashlib

from tcp_module.storage_manager import (
    create_backup,
    register_chunk,
    repair_chunk,
    reconstruct_file,
    check_chunks
)

backup_id = "backup_selective_test"
filename = "sample.txt"

shutil.rmtree("test_storage", ignore_errors=True)

server_roots = {
    "server_1": "test_storage/server_1",
    "server_2": "test_storage/server_2",
    "server_3": "test_storage/server_3"
}

chunks = [
    b"First part ",
    b"Second part ",
    b"Third part"
]

original = b"".join(chunks)
file_hash = hashlib.sha256(original).hexdigest()

create_backup(backup_id, filename, 3, file_hash)

for i, data in enumerate(chunks):
    server_id = "server_" + str(i + 1)

    metadata = {
        "backup_id": backup_id,
        "filename": filename,
        "total_chunks": 3,
        "chunk_id": i,
        "chunk_size": len(data),
        "checksum": hashlib.sha256(data).hexdigest(),
        "server_id": server_id
    }

    register_chunk(backup_id, metadata)

    folder = os.path.join(server_roots[server_id], backup_id)
    os.makedirs(folder, exist_ok=True)

    path = os.path.join(folder, filename + ".chunk_" + str(i))

    with open(path, "wb") as file:
        file.write(data)

# Simulate losing chunk 1
os.remove(
    os.path.join(
        server_roots["server_2"],
        backup_id,
        filename + ".chunk_1"
    )
)

missing, corrupted = check_chunks(backup_id, server_roots)

print("Missing:", missing)
print("Corrupted:", corrupted)

# Recover only chunk 1 from the saved original data
repair_chunk(
    backup_id,
    1,
    chunks[1],
    server_roots
)

missing, corrupted = check_chunks(backup_id, server_roots)

assert missing == []
assert corrupted == []

print("All chunks verified!")

output_path = reconstruct_file(backup_id, server_roots)

with open(output_path, "rb") as file:
    recovered = file.read()

assert recovered == original

print("Selective recovery test passed!")
