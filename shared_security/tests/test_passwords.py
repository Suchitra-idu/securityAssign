from shared_security.passwords import hash_password, verify_password


def test_verify_accepts_correct_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_verify_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_hash_is_salted_per_call():
    assert hash_password("same password") != hash_password("same password")
