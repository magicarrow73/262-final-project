import time

def test_bid_before_user_exists_rejected(solo_db):
    aid = "x"; solo_db.start_auction(aid, int(time.time() + 0.2), "TEST-ITEM", sync=True)
    ok = solo_db.submit_bid(aid, "ghost", 1, sync=True)
    assert ok is True
    assert solo_db.get_user_by_username("ghost") is None

def test_cannot_bid_after_close(solo_db):
    solo_db.create_user("ann", "pw", "Ann", sync=True)
    aid = "y"; solo_db.start_auction(aid, int(time.time() + 0.1), "TEST-ITEM", sync=True)
    time.sleep(0.15)
    solo_db.end_auction(aid, sync=True)
    assert solo_db.submit_bid(aid, "ann", 5, sync=True) is False


def test_single_bidder_pays_zero(solo_db):
    solo_db.create_user("peter", "pw", "Peter", sync=True)
    aid = "z"; solo_db.start_auction(aid, int(time.time() + 0.1), "TEST-ITEM", sync=True)
    solo_db.submit_bid(aid, "peter", 50, sync=True)
    time.sleep(0.15)
    solo_db.end_auction(aid, sync=True)
    assert solo_db.get_auction_result(aid) == ("peter", 50, 0.0)
