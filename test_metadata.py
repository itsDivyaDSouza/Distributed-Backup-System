
import hashlib

from tcp_module.storage_manager import (
    create_backup,
    register_chunk,
    load_manifest
)

backup_id = "backup_test_001"
filename = "sample.txt"

chunk_data = b"Hello distributed backup!"

chunk_hash = hashlib.sha256(chunk_data).hexdigest()
file_hash = hashlib.sha256(chunk_data).hexdigest()

create_backup(
    backup_id,
    filename,
    1,
    file_hash
)

metadata = {
    "backup_id": backup_id,
    "filename": filename,
    "total_chunks": 1,
    "chunk_id": 0,
    "chunk_size": len(chunk_data),
    "checksum": chunk_hash,
    "server_id": "server_1"
}

register_chunk(backup_id, metadata)

manifest = load_manifest(backup_id)

assert manifest is not None
assert manifest["chunks"]["0"]["checksum"] == chunk_hash
assert manifest["chunks"]["0"]["server_id"] == "server_1"

print("Manifest test passed!")
print(manifest)
