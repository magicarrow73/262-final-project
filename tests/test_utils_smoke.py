from system_main.utils import verify_password

def test_verify_password_hash_mismatch():
    assert verify_password("hash123", "different") is False
    assert verify_password("hash123", "hash123") is True
