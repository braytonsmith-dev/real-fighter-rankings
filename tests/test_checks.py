"""Sanity checks that gate the weekly commit (src/mmalab/checks.py)."""
from __future__ import annotations

import pandas as pd

from mmalab import checks


def _ledger(rows):
    cols = ["pick_id", "predicted_at_utc", "event", "event_date", "fighter_a", "fighter_b", "p_a", "pick", "status",
            "p_a_v11", "pick_v11", "v11_locked_at_utc"]
    return pd.DataFrame(rows, columns=cols).fillna("").astype(str)


def test_picks_append_only_passes_on_additions_and_grading():
    old = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.6", "A", "pending", "", "", ""]])
    new = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.6", "A", "correct", "0.62", "A", "t2"],
                   ["2", "t3", "F", "2026-10-17", "C", "D", "0.4", "D", "pending", "", "", ""]])
    assert checks.picks_problems(old, new) == []


def test_picks_lock_field_edit_is_caught():
    old = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.6", "A", "pending", "", "", ""]])
    new = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.7", "A", "pending", "", "", ""]])
    probs = checks.picks_problems(old, new)
    assert any("p_a changed" in p for p in probs)


def test_picks_removal_and_regrade_are_caught():
    old = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.6", "A", "correct", "", "", ""],
                   ["2", "t1", "E", "2026-10-10", "C", "D", "0.6", "C", "pending", "", "", ""]])
    new = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.6", "A", "incorrect", "", "", ""]])
    probs = checks.picks_problems(old, new)
    assert any("removed" in p for p in probs)
    assert any("changed grade" in p for p in probs)


def test_shadow_columns_may_be_filled_once_only():
    old = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.6", "A", "pending", "0.55", "A", "t2"]])
    new = _ledger([["1", "t1", "E", "2026-10-10", "A", "B", "0.6", "A", "pending", "0.58", "A", "t2"]])
    assert any("p_a_v11 changed" in p for p in checks.picks_problems(old, new))


def test_boards_checks_on_a_synthetic_board(tmp_path):
    from mmalab.rankings import RANKED_DIVISIONS
    rows = []
    for div in RANKED_DIVISIONS:
        rows.append({"division": div, "fighter": f"{div} champ", "rank": 0, "score": 1.0, "rating": 1800, "champion": True, "interim": False, "days_since": 30})
        for i in range(1, 17):
            rows.append({"division": div, "fighter": f"{div} {i}", "rank": i, "score": 1.0 - i / 20, "rating": 1700 - i, "champion": False, "interim": False, "days_since": 100})
    df = pd.DataFrame(rows)
    p = tmp_path / "board.csv"
    df.to_csv(p, index=False)
    assert checks.check_boards(p, label="synthetic") == []
    # a gap in the ranks and an over-aged top-15 fighter are both reported
    bad = df.copy()
    bad.loc[(bad["division"] == RANKED_DIVISIONS[0]) & (bad["rank"] == 3), "rank"] = 30
    bad.loc[(bad["division"] == RANKED_DIVISIONS[1]) & (bad["rank"] == 1), "days_since"] = 900
    bad.to_csv(p, index=False)
    probs = checks.check_boards(p, label="synthetic")
    assert any("not 1..n" in x for x in probs)
    assert any("days_since" in x for x in probs)
