def test_create_user_idempotent(solo_db):
    assert solo_db.create_user("alice", "pw", "Alice", sync=True) is True
    assert solo_db.create_user("alice", "pw", "Alice", sync=True) is False


def test_login_logout_cycle(solo_db):
    solo_db.create_user("bob", "hash", "Bob", sync=True)
    assert solo_db.user_login("bob", sync=True) is True
    assert solo_db.user_logout("bob", sync=True) is True
