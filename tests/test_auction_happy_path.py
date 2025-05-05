import time

def test_single_item_second_price(solo_db):
    solo_db.create_user("alice", "pw", "Alice", sync=True)
    solo_db.create_user("bob",   "pw", "Bob",   sync=True)

    aid = "painting-42"
    closes = int(time.time() + 0.4)
    assert solo_db.start_auction(aid, closes, "TEST-ITEM", sync=True) is True

    solo_db.submit_bid(aid, "alice", 35, sync=True)
    solo_db.submit_bid(aid, "bob",   20, sync=True)

    time.sleep(0.5)
    solo_db.end_auction(aid, sync=True)
    winner, win_bid, price = solo_db.get_auction_result(aid)

    assert (winner, win_bid, price) == ("alice", 35, 20)
