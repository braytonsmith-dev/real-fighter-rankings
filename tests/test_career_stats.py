"""Unit tests for mmalab.career_stats: a hand-checked synthetic career, the no-look-ahead property,
NaN handling for bouts without statistics, the control-tracking rule and the style thresholds."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mmalab.career_stats import (CONTRIB_COLS, FEATURE_COLS, NUMERIC_COLS, OWN_STATS, bout_features, career_table,
                                 classify_style, features_as_of)

STAT_DEFAULTS = {c: 0.0 for c in OWN_STATS}


def _bouts(rows: list[dict]) -> pd.DataFrame:
    """Rows carry event, date, fighter_a, fighter_b, result_a, method, fight_seconds and optional
    `a` / `b` dicts of own-side totals; a row with has_stats False gets NaN statistics."""
    out = []
    for i, r in enumerate(rows):
        has = r.get("has_stats", True)
        rec = {"event": r["event"], "date": pd.Timestamp(r["date"]), "bout_id": i, "fighter_a": r["fighter_a"],
               "fighter_b": r["fighter_b"], "result_a": r["result_a"], "method": r["method"],
               "fight_seconds": r["fight_seconds"], "has_stats": has}
        for side in ("a", "b"):
            stats = {**STAT_DEFAULTS, **r.get(side, {})} if has else {c: np.nan for c in OWN_STATS}
            rec.update({f"{c}_{side}": v for c, v in stats.items()})
        out.append(rec)
    return pd.DataFrame(out)


# Alpha's career: a decision win, a KO loss, a submission win, then a KO loss with no statistics.
ALPHA_ROWS = [
    {"event": "E1", "date": "2020-01-10", "fighter_a": "Alpha", "fighter_b": "Bravo", "result_a": 1.0, "method": "U-DEC",
     "fight_seconds": 900,
     "a": {"sig_landed": 60, "sig_att": 120, "td_landed": 2, "td_att": 4, "kd": 1, "ctrl_sec": 180, "head_landed": 40,
           "clinch_landed": 5, "ground_landed": 5},
     "b": {"sig_landed": 30, "sig_att": 100, "td_landed": 0, "td_att": 2, "kd": 0, "ctrl_sec": 60, "head_landed": 20}},
    {"event": "E2", "date": "2020-07-10", "fighter_a": "Charlie", "fighter_b": "Alpha", "result_a": 1.0, "method": "KO/TKO",
     "fight_seconds": 300,
     "a": {"sig_landed": 25, "sig_att": 40, "kd": 1, "ctrl_sec": 30, "head_landed": 15},
     "b": {"sig_landed": 10, "sig_att": 30, "td_landed": 0, "td_att": 1, "clinch_landed": 2}},
    {"event": "E3", "date": "2022-01-10", "fighter_a": "Alpha", "fighter_b": "Delta", "result_a": 1.0, "method": "SUB",
     "fight_seconds": 600,
     "a": {"sig_landed": 20, "sig_att": 50, "td_landed": 3, "td_att": 5, "ctrl_sec": 300, "head_landed": 10,
           "ground_landed": 8},
     "b": {"sig_landed": 15, "sig_att": 40, "td_landed": 0, "td_att": 1, "ctrl_sec": 30, "head_landed": 9}},
    {"event": "E4", "date": "2023-09-10", "fighter_a": "Alpha", "fighter_b": "Echo", "result_a": 0.0, "method": "KO/TKO",
     "fight_seconds": 120, "has_stats": False},
    {"event": "E5", "date": "2024-03-01", "fighter_a": "Echo", "fighter_b": "Foxtrot", "result_a": 0.0, "method": "U-DEC",
     "fight_seconds": 900,
     "a": {"sig_landed": 40, "sig_att": 90, "ctrl_sec": 60}, "b": {"sig_landed": 50, "sig_att": 100, "ctrl_sec": 120}},
]
FIGHTERS = pd.DataFrame({"fighter": ["Alpha", "Bravo"], "dob": ["1990-01-10", None]})


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    return career_table(_bouts(ALPHA_ROWS), FIGHTERS)


def _row(table: pd.DataFrame, fighter: str, bout_id: int) -> pd.Series:
    return table[(table["fighter"] == fighter) & (table["bout_id"] == bout_id)].iloc[0]


class TestSyntheticCareer:
    def test_debut_row_is_empty_history(self, table: pd.DataFrame) -> None:
        r = _row(table, "Alpha", 0)
        assert r["n_bouts"] == 0 and r["n_wins"] == 0 and r["stats_bouts"] == 0 and r["minutes"] == 0
        assert np.isnan(r["slpm"]) and np.isnan(r["layoff_days"]) and np.isnan(r["win_rate_last5"])
        assert r["cum_sig_absorbed"] == 0 and r["ufc_years"] == 0 and r["style"] == "unknown"
        assert r["age"] == pytest.approx(10957 / 365.25)        # 1990-01-10 to 2020-01-10, seven leap days

    def test_rates_before_third_bout_by_hand(self, table: pd.DataFrame) -> None:
        r = _row(table, "Alpha", 2)                              # before E3, after a decision win and a KO loss
        assert (r["n_bouts"], r["n_wins"], r["n_losses"], r["ko_losses"], r["sub_losses"]) == (2, 1, 1, 1, 0)
        assert r["minutes"] == pytest.approx(20.0) and r["stats_minutes"] == pytest.approx(20.0)
        assert r["slpm"] == pytest.approx(70 / 20)              # (60 + 10) landed over 15 + 5 minutes
        assert r["sapm"] == pytest.approx(55 / 20)              # 30 + 25 absorbed
        assert r["sig_acc"] == pytest.approx(70 / 150)
        assert r["sig_def"] == pytest.approx(1 - 55 / 140)
        assert r["td_avg"] == pytest.approx(2 / 20 * 15)
        assert r["td_rate"] == pytest.approx(5 / 20 * 15)
        assert r["td_acc"] == pytest.approx(2 / 5) and r["td_def"] == pytest.approx(1.0)
        assert r["ctrl_share"] == pytest.approx(180 / 1200) and r["ctrl_against_share"] == pytest.approx(90 / 1200)
        assert r["kd_for_per15"] == pytest.approx(0.75) and r["kd_against_per15"] == pytest.approx(0.75)
        assert r["cum_sig_absorbed"] == 55 and r["cum_head_absorbed"] == 35 and r["cum_kd_against"] == 1
        assert r["grappling_share"] == pytest.approx(12 / 70)   # clinch 5 + ground 5 + clinch 2
        assert r["finish_rate_for"] == 0.0 and r["finished_rate_against"] == 1.0
        assert r["win_rate_last5"] == pytest.approx(0.5)
        assert r["style"] == "mixed"                             # 3.75 attempts per 15 and 15% control

    def test_recency_layoff_activity_and_age(self, table: pd.DataFrame) -> None:
        r = _row(table, "Alpha", 2)
        assert r["ko_losses_3y"] == 1 and r["last_ko_loss_days"] == 549 and r["layoff_days"] == 549
        assert r["bouts_3y"] == 2
        assert r["ufc_years"] == pytest.approx(731 / 365.25)
        assert r["bouts_per_year"] == pytest.approx(2 / (731 / 365.25))
        assert r["age"] == pytest.approx(32.0, abs=1e-6)
        r4 = _row(table, "Alpha", 3)                             # before E4: the KO loss has aged out of the window
        assert r4["ko_losses"] == 1 and r4["ko_losses_3y"] == 0 and r4["last_ko_loss_days"] == 1157
        assert r4["bouts_3y"] == 1 and r4["bouts_per_year"] == pytest.approx(1 / 3)   # tenure 3.67 years, capped at 3
        assert r4["layoff_days"] == 608 and r4["slpm"] == pytest.approx(90 / 30)
        assert r4["finish_rate_for"] == pytest.approx(0.5) and r4["win_rate_last5"] == pytest.approx(2 / 3)

    def test_bout_contribution_columns_roll_the_history_forward(self, table: pd.DataFrame) -> None:
        r2, r3 = _row(table, "Alpha", 1), _row(table, "Alpha", 2)
        assert r2["bout_result"] == 0.0 and r2["bout_method"] == "KO/TKO" and r2["bout_ko_loss"] == 1
        assert r3["ko_losses"] == r2["ko_losses"] + r2["bout_ko_loss"]
        assert r3["cum_sig_absorbed"] == r2["cum_sig_absorbed"] + r2["bout_sig_absorbed"]
        assert r3["minutes"] == pytest.approx(r2["minutes"] + r2["bout_minutes"])
        assert all(f"bout_{c}" in table.columns for c in CONTRIB_COLS)

    def test_opponent_rows_see_the_same_bout_from_the_other_side(self, table: pd.DataFrame) -> None:
        c = _row(table, "Charlie", 1)
        assert c["n_bouts"] == 0 and c["bout_result"] == 1.0 and c["bout_ko_win"] == 1
        assert c["bout_sig_absorbed"] == 10 and c["bout_kd"] == 1 and c["opponent"] == "Alpha"


class TestMissingStats:
    def test_bout_without_stats_counts_as_a_bout_but_adds_no_statistics(self, table: pd.DataFrame) -> None:
        e = _row(table, "Echo", 4)                               # Echo's only prior bout is the stats-free E4
        assert e["n_bouts"] == 1 and e["n_wins"] == 1 and e["stats_bouts"] == 0
        assert e["minutes"] == pytest.approx(2.0) and e["stats_minutes"] == 0
        for c in ("slpm", "sapm", "sig_acc", "td_avg", "ctrl_share", "cum_sig_absorbed", "cum_kd_against"):
            assert np.isnan(e[c]), c
        assert e["style"] == "unknown" and e["layoff_days"] == 173
        a = features_as_of(_bouts(ALPHA_ROWS), "2024-01-01", FIGHTERS).loc["Alpha"]
        assert a["n_bouts"] == 4 and a["stats_bouts"] == 3 and a["ko_losses"] == 2 and a["ko_losses_3y"] == 1
        assert a["minutes"] == pytest.approx(32.0) and a["slpm"] == pytest.approx(90 / 30)   # E4 adds no rate minutes
        assert a["cum_sig_absorbed"] == 70 and a["last_ko_loss_days"] == 113 and a["layoff_days"] == 113

    def test_control_share_uses_only_events_where_control_was_recorded(self) -> None:
        rows = [
            {"event": "Old", "date": "1996-05-01", "fighter_a": "Golf", "fighter_b": "Hotel", "result_a": 1.0, "method": "SUB",
             "fight_seconds": 600, "a": {"sig_landed": 10, "sig_att": 20}, "b": {"sig_landed": 5, "sig_att": 10}},
            {"event": "New", "date": "2001-05-01", "fighter_a": "Golf", "fighter_b": "India", "result_a": 1.0, "method": "U-DEC",
             "fight_seconds": 900, "a": {"sig_landed": 30, "sig_att": 60, "ctrl_sec": 300}, "b": {"sig_landed": 20, "sig_att": 50, "ctrl_sec": 60}},
            {"event": "Later", "date": "2002-05-01", "fighter_a": "Golf", "fighter_b": "Juliet", "result_a": 0.0, "method": "U-DEC",
             "fight_seconds": 900, "a": {"sig_landed": 1, "sig_att": 2}, "b": {"sig_landed": 2, "sig_att": 4}},
        ]
        t = career_table(_bouts(rows), FIGHTERS)
        before_new = _row(t, "Golf", 1)
        assert before_new["stats_minutes"] == 10 and before_new["ctrl_minutes"] == 0 and np.isnan(before_new["ctrl_share"])
        assert before_new["slpm"] == pytest.approx(1.0)        # strike rates still use the untracked bout
        before_later = _row(t, "Golf", 2)
        assert before_later["ctrl_minutes"] == 15 and before_later["ctrl_share"] == pytest.approx(300 / 900)
        assert before_later["ctrl_against_share"] == pytest.approx(60 / 900)


class TestNoLookAhead:
    def test_as_of_equals_the_next_bout_row(self) -> None:
        bouts = _bouts(ALPHA_ROWS)
        t = career_table(bouts, FIGHTERS)
        for d in bouts["date"].unique():
            f = features_as_of(bouts, d, FIGHTERS)
            day = t[t["date"] == d].set_index("fighter")
            debut, seen = day[day["n_bouts"] == 0], day[day["n_bouts"] > 0]
            assert not debut.index.isin(f.index).any()
            assert set(seen.index) <= set(f.index)
            for name in seen.index:
                for c in FEATURE_COLS:
                    x, y = seen.loc[name, c], f.loc[name, c]
                    if c == "style":
                        assert x == y
                    else:
                        assert (np.isnan(x) and np.isnan(y)) or x == pytest.approx(y), (name, c, x, y)

    def test_appending_future_bouts_leaves_earlier_rows_unchanged(self) -> None:
        bouts = _bouts(ALPHA_ROWS)
        short = career_table(bouts[bouts["date"] < "2022-01-01"], FIGHTERS)
        full = career_table(bouts, FIGHTERS)
        full = full[full["date"] < "2022-01-01"].reset_index(drop=True)
        pd.testing.assert_frame_equal(short.reset_index(drop=True), full)

    def test_as_of_before_any_bout_is_empty_and_as_of_ignores_later_bouts(self) -> None:
        bouts = _bouts(ALPHA_ROWS)
        assert features_as_of(bouts, "2019-01-01", FIGHTERS).empty
        a = features_as_of(bouts, "2021-01-01", FIGHTERS)
        b = features_as_of(bouts[bouts["date"] < "2021-01-01"], "2021-01-01", FIGHTERS)
        pd.testing.assert_frame_equal(a, b)
        assert set(a.index) == {"Alpha", "Bravo", "Charlie"}
        assert a.loc["Alpha", "n_bouts"] == 2 and a.loc["Alpha", "layoff_days"] == 175    # 2020-07-10 to 2021-01-01
        assert a.loc["Alpha", "last_bout_date"] == pd.Timestamp("2020-07-10")


class TestBoutFeatures:
    def test_sides_and_differences(self) -> None:
        bf = bout_features(_bouts(ALPHA_ROWS), FIGHTERS)
        assert bf.index.name == "bout_id" and list(bf.index) == [0, 1, 2, 3, 4]
        r = bf.loc[2]
        assert r["fighter_a"] == "Alpha" and r["fighter_b"] == "Delta"
        assert r["n_bouts_a"] == 2 and r["n_bouts_b"] == 0 and r["n_bouts_diff"] == 2
        assert r["slpm_a"] == pytest.approx(3.5) and np.isnan(r["slpm_b"]) and np.isnan(r["slpm_diff"])
        assert r["style_a"] == "mixed" and r["style_b"] == "unknown"
        assert not any(c.startswith("bout_") for c in bf.columns)
        assert all(f"{c}_{s}" in bf.columns for c in NUMERIC_COLS for s in ("a", "b", "diff"))


class TestStyleThresholds:
    def test_cut_points(self) -> None:
        td = pd.Series([5.0, 4.99, 2.49, 2.5, 3.0, 6.0, 1.0, 6.0, 1.0, 9.0])
        ctrl = pd.Series([0.25, 0.30, 0.149, 0.10, 0.20, 0.10, 0.30, np.nan, np.nan, 0.5])
        n = pd.Series([3, 3, 3, 3, 3, 3, 3, 3, 3, 0])
        got = classify_style(td, ctrl, n).tolist()
        assert got == ["wrestler", "mixed", "striker", "mixed", "mixed", "mixed", "mixed", "wrestler", "striker", "unknown"]

    def test_unknown_without_statistics_even_with_bouts(self, table: pd.DataFrame) -> None:
        assert _row(table, "Echo", 4)["style"] == "unknown"
        assert set(table["style"].unique()) <= {"wrestler", "striker", "mixed", "unknown"}
