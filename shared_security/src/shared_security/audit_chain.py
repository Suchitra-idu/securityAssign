import hashlib

GENESIS_HASH = bytes(32)


def compute_chain_hash(previous_hash: bytes, record: bytes) -> bytes:
    return hashlib.sha256(previous_hash + record).digest()


def verify_chain(chain: list[tuple[bytes, bytes]]) -> bool:
    previous = GENESIS_HASH
    for record, stored_hash in chain:
        if compute_chain_hash(previous, record) != stored_hash:
            return False
        previous = stored_hash
    return True
