from shared_security.audit_chain import (
    GENESIS_HASH,
    compute_chain_hash,
    verify_chain,
)


def _build(records):
    chain, prev = [], GENESIS_HASH
    for rec in records:
        prev = compute_chain_hash(prev, rec)
        chain.append((rec, prev))
    return chain


def test_hash_is_deterministic():
    a = compute_chain_hash(GENESIS_HASH, b"record")
    b = compute_chain_hash(GENESIS_HASH, b"record")
    assert a == b


def test_hash_depends_on_previous():
    a = compute_chain_hash(GENESIS_HASH, b"record")
    b = compute_chain_hash(b"\x01" * 32, b"record")
    assert a != b


def test_valid_chain_verifies():
    assert verify_chain(_build([b"a", b"b", b"c"]))


def test_tampered_record_breaks_chain():
    chain = _build([b"a", b"b", b"c"])
    chain[1] = (b"tampered", chain[1][1])
    assert not verify_chain(chain)


def test_tampered_hash_breaks_chain():
    chain = _build([b"a", b"b", b"c"])
    chain[1] = (chain[1][0], bytes(32))
    assert not verify_chain(chain)
