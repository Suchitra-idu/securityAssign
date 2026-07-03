from shared_security.tokens import generate_signing_keypair
from shared_security.transaction_signatures import sign_transaction, verify_transaction


def _tx():
    return {"from": "acc-1", "to": "acc-2", "amount": 100, "currency": "GBP"}


def test_round_trip_verifies(keypair):
    priv, pub = keypair
    assert verify_transaction(_tx(), sign_transaction(_tx(), priv), pub)


def test_tampered_field_fails(keypair):
    priv, pub = keypair
    tx = _tx()
    sig = sign_transaction(tx, priv)
    tx["amount"] = 1_000_000
    assert not verify_transaction(tx, sig, pub)


def test_wrong_key_fails(keypair):
    priv, _ = keypair
    _, other_pub = generate_signing_keypair()
    sig = sign_transaction(_tx(), priv)
    assert not verify_transaction(_tx(), sig, other_pub)


def test_field_order_does_not_matter(keypair):
    # Canonical serialisation must make key order irrelevant, so a signature
    # over a dict from the DB still verifies regardless of column ordering.
    priv, pub = keypair
    sig = sign_transaction({"from": "a", "to": "b", "amount": 5}, priv)
    assert verify_transaction({"amount": 5, "to": "b", "from": "a"}, sig, pub)
