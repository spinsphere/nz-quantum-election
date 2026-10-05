"""MMP seat allocation for the New Zealand House of Representatives.

Implements the Sainte-Laguë method used by the Electoral Commission:
  * 120 nominal seats
  * a party qualifies for list seats with >= 5% of the party vote OR at least
    one electorate seat
  * each qualifying party's share of the 120 seats is found with the
    Sainte-Laguë divisor sequence 1, 3, 5, 7, ...
  * a party that wins more electorates than its entitlement keeps them all,
    and the House grows by the difference (overhang)
"""

from __future__ import annotations


def sainte_lague(votes_pct: dict[str, float], electorates: dict[str, int],
                 total_seats: int = 120, threshold_pct: float = 5.0) -> dict[str, int]:
    """Return seats per party under MMP rules.

    votes_pct: party vote share in percent (parties not listed are treated as
               'other' and ignored, as the Commission does for non-qualifying votes)
    electorates: electorate seats won by each party (missing -> 0)
    """
    eligible = {p: v for p, v in votes_pct.items()
                if v >= threshold_pct or electorates.get(p, 0) > 0}
    alloc = {p: 0 for p in eligible}
    for _ in range(total_seats):
        winner = max(eligible, key=lambda p: eligible[p] / (2 * alloc[p] + 1))
        alloc[winner] += 1
    seats = {}
    for p in votes_pct:
        seats[p] = max(alloc.get(p, 0), electorates.get(p, 0))  # overhang keeps electorates
    return seats


def majority_threshold(total_seats: int) -> int:
    """Smallest number of seats that is a majority of the House."""
    return total_seats // 2 + 1


if __name__ == "__main__":
    import json
    data = json.load(open("policy_data.json"))
    meta = data["metadata"]
    parties = list(data["parties"])
    votes = {p: meta["polling_average"][p] for p in parties}
    elect = {p: meta["electorate_assumptions"].get(p, 0) for p in parties}
    seats = sainte_lague(votes, elect)
    total = sum(seats.values())
    print(f"{'Party':<14}{'Vote %':>8}{'Electorates':>13}{'Seats':>7}")
    for p in parties:
        print(f"{p:<14}{votes[p]:>8.1f}{elect[p]:>13}{seats[p]:>7}")
    print(f"{'TOTAL':<14}{'':>8}{'':>13}{total:>7}   majority = {majority_threshold(total)}")
