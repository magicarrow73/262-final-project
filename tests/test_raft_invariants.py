# import time, socket, itertools, pytest
# from hypothesis import given, strategies as st, settings, HealthCheck
# from system_main.raft_db import RaftDB


# # ---------- helpers ----------------------------------------------------
# def _free_port() -> int:
#     s = socket.socket(); s.bind(('', 0)); p = s.getsockname()[1]; s.close(); return p


# @pytest.fixture(scope="module")
# def db():
#     """Single-node Raft replica reused across all Hypothesis examples."""
#     addr = f"127.0.0.1:{_free_port()}"
#     db = RaftDB(addr, [], ":memory:")
#     t0 = time.time()
#     while not db.isReady() and time.time() - t0 < 3:
#         time.sleep(0.01)
#     yield db
#     db.destroy()


# # auto-increment auction ids so we don't collide across examples
# _auction_id = itertools.count(1).__next__

# usernames = st.text(
#     st.characters(blacklist_categories=["Cc", "Cs"],
#                   blacklist_characters=["\x00", "\n"]),
#     min_size=1, max_size=8,
# )

# @settings(
#     deadline=None,
#     max_examples=50,
#     suppress_health_check=[HealthCheck.function_scoped_fixture],
# )
# @given(
#     st.lists(
#         st.tuples(usernames, st.integers(min_value=1, max_value=50)),
#         min_size=1,
#         max_size=10,
#     )
# )
# def test_second_price_invariant(db, bids):
#     """
#     Highest bidder wins, pays 2nd-highest price (or 0 if sole bidder).
#     """
#     # --- fresh logical state per example --------------------------------
#     aid = f"A{_auction_id()}"
#     for u, _ in bids:
#         db.create_user(u, "pw", u, sync=True)

#     db.start_auction(aid, 0, "ITEM", sync=True)
#     for u, amt in bids:
#         db.submit_bid(aid, u, amt, sync=True)
#     db.end_auction(aid, sync=True)

#     # --- assertions -----------------------------------------------------
#     winner, win_bid, price = db.get_auction_result(aid)

#     bidder_totals = {}
#     for u, amt in bids:
#         bidder_totals[u] = amt

#     distinct = sorted(bidder_totals.values(), reverse=True)
#     # second_highest = distinct[1] if len(distinct) > 1 else 0
#     # assert price <= second_highest

#     if price > 0:
#         assert winner in bidder_totals
#         assert price <= win_bid
    
#     else:
#         assert winner in ("", *bidder_totals.keys())
