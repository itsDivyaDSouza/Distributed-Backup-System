Distributed Backup System — TCP File Transfer
1. Module Overview

This module implements TCP-based file transfer between a client and a backup server. It divides files into chunks, transfers them over a TCP connection, verifies chunk integrity, reconstructs the original file, and verifies the complete file using SHA-256.
2. Files

    client.py — reads the input file, calculates its checksum, divides it into chunks, sends the chunks, and receives server acknowledgements.

    server.py — receives chunks, validates their checksums, saves them, reconstructs the file, and verifies the complete-file checksum.

    received_chunks/ — stores received chunks and reconstructed files.

    sample.txt — small text-file test input.

    large_sample.bin — large binary-file test input.
3. Technologies Used

    Python 3

    TCP sockets

    JSON metadata

    SHA-256 checksums

    Binary file handling

4. Configuration

    Server bind address: 0.0.0.0

    TCP port: 5001

    Chunk size: 65,536 bytes

    Receive buffer: 4,096 bytes

The client currently connects to 127.0.0.1, so the client and server can be tested on the same machine. For deployment across different machines or Mininet hosts, the client address must be configured to use the appropriate server IP address.
5. How to Run

Start the server in Terminal 1:

cd ~/distributed_backup
python3 server.py

Start the client in Terminal 2:

cd ~/distributed_backup
python3 client.py

Enter the file path when prompted, for example:

sample.txt

or:

large_sample.bin

6. Transfer Protocol

    The client opens a TCP connection to the server.

    The client sends JSON metadata preceded by a four-byte network-order message length.

    The client sends the corresponding binary chunk.

    The server verifies the chunk's SHA-256 checksum and stores valid chunks.

    The server acknowledges successfully received chunks.

    After all chunks have been sent, the client sends a completion message containing the whole-file SHA-256 checksum.

    The server reconstructs the file and compares its SHA-256 checksum against the client's checksum.

    The server reports successful verification if the checksums match.

7. Testing and Results
Test 1: Large Binary File

    Input: large_sample.bin

    File size: 204,800 bytes

    Expected number of chunks: 4

    Result: Transfer and whole-file checksum verification succeeded.

    Additional verification: cmp reported no differences between the original and reconstructed files, and their SHA-256 hashes matched.

Test 2: Small Text File

    Input: sample.txt

    Result: Transfer and whole-file checksum verification succeeded.

    Additional verification: cmp reported no differences between the original and reconstructed files, and their SHA-256 hashes matched.

8. Current Scope and Integration Notes

This module provides basic TCP file transfer, per-chunk integrity verification, file reconstruction, and whole-file checksum verification.

The following functions are outside the current implementation and require integration with the other project modules:

    Distributing chunks across multiple backup servers.

    Tracking missing or corrupted chunks for selective retransmission.

    Resuming interrupted transfers by sending only missing or corrupted chunks.

    Integration with the Mininet/SDN network topology.

The client currently uses a loopback address for local testing. The address and protocol must be coordinated with the other team members during integration.
9. Conclusion

The TCP file-transfer component has been tested using both a small text file and a larger binary file. In both tests, the reconstructed file matched the original, and whole-file SHA-256 verification succeeded.
