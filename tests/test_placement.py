"""Synthetic cases for mmalab.placement: the constraint collector and the ordering solver.
Run with: PYTHONPATH=src python3 -m pytest tests/test_placement.py -q"""
from __future__ import annotations

import random

import pandas as pd
import pytest

from mmalab import placement as pl

AS_OF = pd.Timestamp("2026-10-20")
CFG = {"head_to_head": {"max_gap": 3, "max_gap_recent": 6, "max_years": 3},
       "title_cycle": {"days": 270, "min_position": 4, "release_top10_wins": 1, "release_wins": 2}}


def bouts(rows: list[tuple]) -> pd.DataFrame:
    """rows: (days_before_as_of, winner, loser[, flags]) with flags among close, title, interim, top10, draw."""
    recs = []
    for i, r in enumerate(rows):
        days, a, b = r[:3]
        flags = set(r[3]) if len(r) > 3 else set()
        recs.append({"bout_id": i, "date": AS_OF - pd.Timedelta(days=days), "fighter_a": a, "fighter_b": b,
                     "result_a": 0.5 if "draw" in flags else 1.0, "close": "close" in flags,
                     "title_fight": "title" in flags, "interim": "interim" in flags, "top10_win": "top10" in flags,
                     "division": "Test"})
    return pd.DataFrame(recs)


def board(order: list[str], division: str = "Test") -> pd.DataFrame:
    return pd.DataFrame({"division": division, "fighter": order, "pos": range(1, len(order) + 1), "score": 0.0})


def solved_order(frame: pd.DataFrame, division: str = "Test") -> list[str]:
    return list(frame[frame["division"] == division].sort_values("pos")["fighter"])


def test_single_swap():
    out = bouts([(100, "A", "B")])
    cont, notes, report = pl.apply_to_board(board(["B", "A", "C"]), out, AS_OF, CFG)
    assert solved_order(cont) == ["A", "B", "C"]
    assert notes == [f"Test: A moved above B (won {(AS_OF - pd.Timedelta(days=100)).date()})"]
    assert report["moved"] == 2 and report["top15_changed"] == 2 and report["max_displacement"] == 1
    assert pl.violations(solved_order(cont), report["divisions"]["Test"]["constraints"]) == []


def test_chain_lifts_the_whole_chain():
    out = bouts([(100, "A", "B"), (200, "B", "C")])
    cont, notes, _ = pl.apply_to_board(board(["C", "B", "A", "D"]), out, AS_OF, CFG)
    assert solved_order(cont) == ["A", "B", "C", "D"]
    assert [n.split(": ")[1].split(" (")[0] for n in notes] == ["B moved above C", "A moved above B"]


def test_two_winners_over_one_loser_keep_score_order():
    out = bouts([(300, "W1", "L"), (100, "W2", "L")])
    cont, _, _ = pl.apply_to_board(board(["L", "W2", "W1", "X"]), out, AS_OF, CFG)
    assert solved_order(cont) == ["W2", "W1", "L", "X"]      # the sequential rule would order them by meeting date


def test_gap_rule_uses_the_score_order():
    old, recent = 500, 100
    far = ["L", "x1", "x2", "x3", "W", "y"]                      # W sits 4 below L
    assert pl.collect_constraints(far, bouts([(old, "W", "L")]), AS_OF, CFG) == []
    assert len(pl.collect_constraints(far, bouts([(recent, "W", "L")]), AS_OF, CFG)) == 1
    very_far = ["L", "a", "b", "c", "d", "e", "f", "W"]           # 7 below: beyond the recent allowance too
    assert pl.collect_constraints(very_far, bouts([(recent, "W", "L")]), AS_OF, CFG) == []
    near = ["L", "x1", "x2", "W"]
    assert pl.collect_constraints(near, bouts([(old, "W", "L", {"close"})]), AS_OF, CFG) == []   # close and old: void
    assert len(pl.collect_constraints(near, bouts([(recent, "W", "L", {"close"})]), AS_OF, CFG)) == 1
    # a close old win also voids the pair's earlier decisive meeting
    assert pl.collect_constraints(near, bouts([(900, "W", "L"), (old, "L", "W", {"close"})]), AS_OF, CFG) == []
    # the most recent meeting decides
    cons = pl.collect_constraints(["W", "x", "L"], bouts([(900, "W", "L"), (recent, "L", "W")]), AS_OF, CFG)
    assert [(c.fighter, c.other) for c in cons if c.kind == pl.PRECEDENCE] == [("L", "W")]


def test_negative_last_five_forfeits_the_lift():
    losses = [(400 + 10 * i, f"o{i}", "A") for i in range(4)]    # A lost four of his last five
    out = bouts(losses + [(100, "A", "B")])
    assert "A" in pl.negative_form(out)
    assert pl.collect_constraints(["B", "A"], out, AS_OF, CFG) == []
    cont, notes, _ = pl.apply_to_board(board(["B", "A"]), out, AS_OF, CFG)
    assert solved_order(cont) == ["B", "A"] and notes == []
    # control: 3-2 is not negative
    out2 = bouts(losses[:2] + [(300, "A", "p"), (200, "A", "q"), (100, "A", "B")])
    assert "A" not in pl.negative_form(out2)
    assert len(pl.collect_constraints(["B", "A"], out2, AS_OF, CFG)) == 1


def test_cap_with_victim_held_below():
    out = bouts([(400, "Champ", "Old", {"title"}),          # Champ wins the belt (Old was not defending: no cap now, too old)
                 (100, "Champ", "C", {"title"}),            # C loses a title fight as challenger: capped
                 (200, "C", "N")])                          # C beat N within 365 days: N stays below C
    order = ["C", "N", "D", "E", "F", "G"]
    cons = pl.collect_constraints(order, out, AS_OF, CFG)
    assert pl.cap("C", 4, pl.TITLE_LOSS, AS_OF - pd.Timedelta(days=100)) in cons
    assert pl.precedence("C", "N", pl.VICTIM, AS_OF - pd.Timedelta(days=200), lift=False) in cons
    cont, notes, report = pl.apply_to_board(board(order), out, AS_OF, CFG)
    assert solved_order(cont) == ["D", "E", "F", "C", "N", "G"]
    assert notes == [f"Test: C #1 -> #4 (lost a title fight {(AS_OF - pd.Timedelta(days=100)).date()}; the champion fights someone else next)",
                     "Test: N #2 -> #5 (lost to a fighter held by the title-cycle rule in the last year)"]
    assert report["dropped"] == []
    # two victims keep their score order below the capped fighter (the sequential loop reverses them)
    out2 = bouts([(100, "Champ", "C", {"title"}), (200, "C", "N1"), (150, "C", "N2")])
    cont2, _, _ = pl.apply_to_board(board(["N1", "N2", "C", "D", "E", "F"]), out2, AS_OF, CFG)
    assert solved_order(cont2) == ["D", "E", "F", "C", "N1", "N2"]


def test_cap_exemptions_and_release():
    # a champion who lost the belt while defending is exempt
    out = bouts([(400, "X", "Y", {"title"}), (100, "Z", "X", {"title"})])
    assert pl.capped_fighters(out, AS_OF, CFG["title_cycle"]) == {}
    # a challenger is capped until a top-10 win or two wins
    out = bouts([(100, "Champ", "C", {"title"})])
    assert list(pl.capped_fighters(out, AS_OF, CFG["title_cycle"])) == ["C"]
    out = bouts([(100, "Champ", "C", {"title"}), (50, "C", "P", {"top10"})])
    assert pl.capped_fighters(out, AS_OF, CFG["title_cycle"]) == {}
    out = bouts([(100, "Champ", "C", {"title"}), (60, "C", "P"), (30, "C", "Q")])
    assert pl.capped_fighters(out, AS_OF, CFG["title_cycle"]) == {}
    out = bouts([(100, "Champ", "C", {"title"}), (60, "C", "P")])
    assert list(pl.capped_fighters(out, AS_OF, CFG["title_cycle"])) == ["C"]
    # older than the window: no cap
    out = bouts([(300, "Champ", "C", {"title"})])
    assert pl.capped_fighters(out, AS_OF, CFG["title_cycle"]) == {}
    # too few eligible fighters: the cap is relaxed and reported
    out = bouts([(100, "Champ", "C", {"title"})])
    cont, notes, report = pl.apply_to_board(board(["C", "D"]), out, AS_OF, CFG)
    assert solved_order(cont) == ["D", "C"] and len(report["dropped"]) == 1 and "too few eligible" in notes[-1]


def test_reserved_spot_waives_an_old_head_to_head_of_a_capped_fighter():
    out = bouts([(100, "Champ", "C", {"title"}), (400, "C", "V")])   # C beat V 400 days ago: V is not a recent victim
    order = ["V", "C", "D", "E", "F"]
    cons = pl.collect_constraints(order, out, AS_OF, CFG)
    assert pl.precedence("C", "V", pl.H2H, AS_OF - pd.Timedelta(days=400)) in cons
    final, applied, dropped = pl.solve(order, cons)
    assert final == ["V", "D", "E", "C", "F"]               # V takes a reserved spot, as the sequential fill allows
    assert [c.reason for c in dropped] == [pl.H2H]
    strict, _, dropped_strict = pl.solve(order, cons, waive=False)
    assert strict == ["D", "E", "F", "C", "V"] and dropped_strict == []
    # a recent victim is held, waiver or not
    out2 = bouts([(100, "Champ", "C", {"title"}), (200, "C", "V")])
    cont, _, _ = pl.apply_to_board(board(order), out2, AS_OF, CFG)
    assert solved_order(cont) == ["D", "E", "F", "C", "V"]


def test_cycle_is_broken_by_dropping_the_oldest_meeting():
    d = lambda s: pd.Timestamp(s)
    cons = [pl.precedence("A", "B", pl.H2H, d("2026-02-01")), pl.precedence("B", "C", pl.H2H, d("2026-01-01")),
            pl.precedence("C", "A", pl.H2H, d("2025-06-01"))]
    final, applied, dropped = pl.solve(["C", "B", "A"], cons)
    assert final == ["A", "B", "C"]
    assert dropped == [cons[2]] and set(applied) == set(cons[:2])
    # collected from bouts: a capped fighter's old win (victim hold) loses to the rematch the victim won
    out = bouts([(100, "Champ", "C", {"title"}), (200, "C", "N"), (50, "N", "C")])
    order = ["A", "B", "C", "N", "D", "E"]
    cons = pl.collect_constraints(order, out, AS_OF, CFG)
    final, applied, dropped = pl.solve(order, cons)
    assert [c.reason for c in dropped] == [pl.VICTIM]
    assert final.index("N") < final.index("C") and final.index("C") >= 3


def test_settled_result_rides_with_a_lifted_loser():
    out = bouts([(300, "W", "L"), (100, "L", "X")])          # W beat L (settled), L beat X who sits above both
    order = ["X", "W", "L", "Y"]
    cons = pl.collect_constraints(order, out, AS_OF, CFG)
    assert pl.ride("W", "L", pl.SETTLED, AS_OF - pd.Timedelta(days=300)) in cons
    cont, notes, report = pl.apply_to_board(board(order), out, AS_OF, CFG)
    assert solved_order(cont) == ["W", "L", "X", "Y"]
    assert f"Test: W kept above L (won {(AS_OF - pd.Timedelta(days=300)).date()})" in notes
    # a ride never holds anyone: a held winner stays put and the inversion is reported
    out2 = bouts([(100, "Champ", "C", {"title"}), (200, "C", "W"), (300, "W", "L"), (100, "L", "X")])
    order2 = ["X", "W", "L", "C", "Y", "Z"]
    cont2, notes2, report2 = pl.apply_to_board(board(order2), out2, AS_OF, CFG)
    final2 = solved_order(cont2)
    assert final2.index("C") == 3 and final2.index("W") > final2.index("C") and final2.index("L") < final2.index("W")
    assert report2["settled_inverted"] == 1 and any("sits below L despite the win" in n for n in notes2)
    off = {"head_to_head": dict(CFG["head_to_head"], ride_settled="none"), "title_cycle": CFG["title_cycle"]}
    assert not any(c.kind == pl.RIDE for c in pl.collect_constraints(order, out, AS_OF, off))
    with pytest.raises(ValueError):
        pl.build_context(out, AS_OF, {"head_to_head": dict(CFG["head_to_head"], ride_settled="maybe"), "title_cycle": CFG["title_cycle"]})


def test_shuffled_constraints_give_the_same_result():
    rng = random.Random(7)
    names = [f"f{i:02d}" for i in range(24)]
    for trial in range(40):
        order = list(names)
        rng.shuffle(order)
        cons = []
        for _ in range(rng.randint(5, 25)):
            a, b = rng.sample(order, 2)
            date = AS_OF - pd.Timedelta(days=rng.randint(1, 1000))
            kind = rng.random()
            if kind < 0.6:
                cons.append(pl.precedence(a, b, pl.H2H, date))
            elif kind < 0.75:
                cons.append(pl.precedence(a, b, pl.VICTIM, date, lift=False))
            elif kind < 0.9:
                cons.append(pl.ride(a, b, pl.SETTLED, date))
            else:
                cons.append(pl.cap(a, 4, pl.TITLE_LOSS, date))
        base = pl.solve(order, cons)
        assert sorted(base[0]) == sorted(order)
        kept = [c for c in base[1] if c.kind != pl.RIDE]
        assert pl.violations(base[0], kept) == []
        for s in range(6):
            shuffled = list(cons)
            random.Random(100 * trial + s).shuffle(shuffled)
            assert pl.solve(order, shuffled) == base
            assert pl.solve(order, shuffled, waive=False) == pl.solve(order, cons, waive=False)


def test_placement_report_counts_and_apply_shape():
    score = [f"f{i}" for i in range(20)]
    final = list(score)
    final.insert(2, final.pop(17))                              # f17 lifted from #18 to #3
    rep = pl.placement_report(score, final, division="Div")
    assert rep["moved"] == 16 and rep["top15_changed"] == 13 and rep["max_displacement"] == 15
    assert ("f17", 18, 3) in rep["moves"]
    out = bouts([(100, "A", "B"), (100, "P", "Q")])
    cont = pd.concat([board(["B", "A", "C"], "One"), board(["Q", "P"], "Two")], ignore_index=True)
    cont["pos_score"] = cont["pos"]
    res, notes, report = pl.apply_to_board(cont, out, AS_OF, CFG)
    assert set(res.columns) == set(cont.columns) and len(res) == len(cont)
    assert solved_order(res, "One") == ["A", "B", "C"] and solved_order(res, "Two") == ["P", "Q"]
    assert list(res["pos_score"]) == list(cont["pos_score"])     # other columns untouched
    assert sorted(report["divisions"]) == ["One", "Two"] and report["moved"] == 4
