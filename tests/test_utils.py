import importlib
utils = importlib.import_module("system_main.utils")


def test_hash_and_verify_roundtrip():
    pwd = "letmein!"
    hashed = utils.hash_password(pwd)

    assert isinstance(hashed, str) and len(hashed) == 64
    int(hashed, 16)

    assert utils.verify_password(hashed, hashed) is True

    other = utils.hash_password("different")
    assert utils.verify_password(other, hashed) is False


def test_verify_password_handles_exceptions():
    """Pass an object whose __eq__ raises to hit the except branch."""
    class Bad:
        def __eq__(self, other):
            raise RuntimeError("boom")

    assert utils.verify_password(Bad(), "whatever") is False
