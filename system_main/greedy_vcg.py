"""
Greedy VCG (Lehmann–O’Callaghan–Shoham 2002) implementation for single-minded bidders.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Iterable, List, Dict, Tuple

__all__ = ["Bid","greedy_vcg"]

###############################################################################
# Data structures
###############################################################################

@dataclass(frozen=True)
class Bid:
    """A single‑minded bid (S_i, v_i)."""

    bidder_id: str   # globally unique identifier for the bidder
    bundle: int      # bitmask representation of the requested bundle
    value: float     # non‑negative value for *exactly* this bundle

    # --------------------------------------------------------------------
    @staticmethod
    def from_iter(bidder_id: str, items: Iterable[int], value: float) -> "Bid":
        """Build a `Bid` from an iterable of item indices."""
        mask = 0
        for j in items:
            mask |= 1 << j
        return Bid(bidder_id, mask, value)

    # Convenience helpers -------------------------------------------------
    def bundle_size(self) -> int:
        if hasattr(int, "bit_count"):
            return self.bundle.bit_count()
        n, c = self.bundle, 0
        while n:
            n &= n - 1
            c += 1
        return c

    def score(self) -> float:
        k = self.bundle_size()
        return 0.0 if k == 0 else self.value / math.sqrt(k)

###############################################################################
# Core algorithm
###############################################################################

def greedy_vcg(bids: Iterable[Bid], m: int) -> Tuple[List[Bid], Dict[str, float]]:
    """
    Greedy allocation with critical‑value payments.
    """
    bid_list = list(bids)
    bid_list.sort(key=lambda b: (-b.score(), -b.value, b.bidder_id))

    allocated_mask = 0          # bitset of items already allocated
    winners: List[Bid] = []
    thresh_score: Dict[str, float] = {}  # highest conflicting score per winner

    for b in bid_list:
        if b.bundle & allocated_mask:
            # conflict with an already allocated bundle
            for w in winners:
                if b.bundle & w.bundle:
                    thresh_score[w.bidder_id] = max(thresh_score.get(w.bidder_id, 0.0), b.score())
            continue

        # accept the bid
        winners.append(b)
        allocated_mask |= b.bundle
        thresh_score[b.bidder_id] = 0.0

    # payments determined by critical values
    payments: Dict[str, float] = {}
    EPS = 1e-12
    for w in winners:
        t = thresh_score[w.bidder_id]
        if t == 0.0:
            payments[w.bidder_id] = 0.0
        else:
            bump = math.nextafter(t, math.inf) if t != math.inf else t + EPS
            payments[w.bidder_id] = bump * math.sqrt(w.bundle_size())

    return winners, payments
