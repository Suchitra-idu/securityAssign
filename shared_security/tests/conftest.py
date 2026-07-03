import pytest


@pytest.fixture
def keypair():
    from shared_security.tokens import generate_signing_keypair

    return generate_signing_keypair()
