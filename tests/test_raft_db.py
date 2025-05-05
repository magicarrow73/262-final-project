USERNAME = "alice"
PASSWORD = "hash_pw"
DISPLAY  = "Alice A."

def test_create_user_duplicate(local_raftdb):
    db = local_raftdb
    ok1 = db.create_user(USERNAME, PASSWORD, DISPLAY, sync=True)
    ok2 = db.create_user(USERNAME, PASSWORD, DISPLAY, sync=True)
    assert ok1 is True
    assert ok2 is False


def test_single_item_auction_flow(local_raftdb):
    db = local_raftdb
    db.create_user("bob", "x", "Bob", sync=True)
    assert db.start_auction("A1", 60, "guitar", sync=True)
    db.end_auction("A1", sync=True)
    assert db.get_auction_result("A1") == ("", 0.0, 0.0)


def test_second_price_logic(local_raftdb):
    db = local_raftdb
    db.start_auction("A2", 60, "book", sync=True)
    db.submit_bid("A2", "alice", 10.0, sync=True)
    db.submit_bid("A2", "bob",   8.0, sync=True)
    db.end_auction("A2", sync=True)
    winner, winning_bid, price = db.get_auction_result("A2")
    assert (winner, winning_bid, price) == ("alice", 10.0, 8.0)
