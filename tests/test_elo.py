"""Unit tests for mmalab.elo: the expected-score curve and single rating updates."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mmalab.elo import EloParams, expected, run_elo


def _bouts(rows: list[tuple]) -> pd.DataFrame:
    """Rows of (bout_id, date, fighter_a, fighter_b, result_a, method), the columns run_elo reads."""
    df = pd.DataFrame(rows, columns=["bout_id", "date", "fighter_a", "fighter_b", "result_a", "method"])
    df["date"] = pd.to_datetime(df["date"])
    df["division"] = "Lightweight"
    return df


class TestExpected:
    def test_equal_ratings_are_a_coin_flip(self) -> None:
        assert expected(1500.0, 1500.0) == 0.5
        assert expected(1234.5, 1234.5) == 0.5

    @pytest.mark.parametrize("ra, rb", [(1500.0, 1600.0), (1700.0, 1450.0), (1500.0, 1500.0), (900.0, 2100.0)])
    def test_symmetry(self, ra: float, rb: float) -> None:
        assert expected(ra, rb) + expected(rb, ra) == pytest.approx(1.0)

    def test_four_hundred_points_is_ten_to_one(self) -> None:
        assert expected(1900.0, 1500.0) == pytest.approx(10 / 11)
        assert expected(1500.0, 1900.0) == pytest.approx(1 / 11)

    def test_monotone_in_own_rating_and_bounded(self) -> None:
        ratings = np.linspace(800, 2400, 50)
        probs = [expected(r, 1500.0) for r in ratings]
        assert all(b > a for a, b in zip(probs, probs[1:]))
        assert 0.0 < min(probs) and max(probs) < 1.0


class TestRunElo:
    def test_debut_decision_moves_each_side_by_half_the_new_fighter_k(self) -> None:
        p = EloParams()
        out, hist = run_elo(_bouts([(1, "2024-01-01", "A", "B", 1.0, "U-DEC")]), p)
        row = out.iloc[0]
        assert row["elo_pre_a"] == row["elo_pre_b"] == p.start
        assert row["p_a"] == 0.5
        step = p.k * p.k_new_mult * 0.5                      # 40 x 1.5 x (1 - 0.5) = 30
        assert row["elo_post_a"] == pytest.approx(p.start + step)
        assert row["elo_post_b"] == pytest.approx(p.start - step)
        assert len(hist) == 2 and set(hist["fighter"]) == {"A", "B"}
        assert hist["ufc_fights"].tolist() == [1, 1]

    def test_finish_and_split_decision_multipliers(self) -> None:
        p = EloParams()
        base = p.k * p.k_new_mult * 0.5
        ko, _ = run_elo(_bouts([(1, "2024-01-01", "A", "B", 1.0, "KO/TKO")]), p)
        split, _ = run_elo(_bouts([(1, "2024-01-01", "A", "B", 1.0, "S-DEC")]), p)
        assert ko.iloc[0]["elo_post_a"] - p.start == pytest.approx(base * p.finish_mult)
        assert split.iloc[0]["elo_post_a"] - p.start == pytest.approx(base * p.split_mult)

    def test_draw_between_equals_and_no_contest_change_nothing(self) -> None:
        p = EloParams()
        out, hist = run_elo(_bouts([
            (1, "2024-01-01", "A", "B", 0.5, "U-DEC"),
            (2, "2024-02-01", "C", "D", np.nan, "NC"),
        ]), p)
        assert (out["elo_post_a"] == p.start).all() and (out["elo_post_b"] == p.start).all()
        assert len(hist) == 2                                 # the draw is rated, the no-contest is not
        assert set(hist["fighter"]) == {"A", "B"}

    def test_ratings_carry_over_and_zero_sum_when_k_matches(self) -> None:
        p = EloParams(k_new_mult=1.0)                         # same K for both sides
        out, _ = run_elo(_bouts([
            (1, "2024-01-01", "A", "B", 1.0, "U-DEC"),
            (2, "2024-03-01", "B", "A", 1.0, "U-DEC"),        # B listed first, wins the rematch
        ]), p)
        second = out.iloc[1]
        assert second["elo_pre_a"] == pytest.approx(p.start - 20)     # B carries the first loss in
        assert second["elo_pre_b"] == pytest.approx(p.start + 20)
        assert second["p_a"] < 0.5                                     # B is the underdog going in
        total = (out["elo_post_a"] + out["elo_post_b"]).to_numpy()
        np.testing.assert_allclose(total, 2 * p.start)                 # classic Elo is zero-sum

    def test_bouts_are_processed_in_date_order_not_input_order(self) -> None:
        p = EloParams()
        later_first = _bouts([
            (2, "2024-06-01", "A", "C", 1.0, "U-DEC"),
            (1, "2024-01-01", "A", "B", 1.0, "U-DEC"),
        ])
        out, _ = run_elo(later_first, p)
        assert out["bout_id"].tolist() == [1, 2]
        assert out.iloc[1]["elo_pre_a"] > p.start
