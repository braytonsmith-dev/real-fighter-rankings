"""Unit tests for the pure helpers in mmalab.resume_board on tiny synthetic frames."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mmalab.resume_board import (
    _merge,
    bad_losses_last_five,
    horizon_weight,
    idr_scale,
    last_five,
    tiered_form_penalty,
)

HORIZONS = {3.0: 1.0, 5.0: 0.6, 10.0: 0.3, 15.0: 0.1}   # as build() passes them: float keys


def _bouts(rows: list[tuple]) -> pd.DataFrame:
    """Rows of (bout_id, date, fighter_a, fighter_b, result_a, rank_a, rank_b) in the engine's output shape."""
    df = pd.DataFrame(rows, columns=["bout_id", "date", "fighter_a", "fighter_b", "result_a", "rank_a", "rank_b"])
    df["date"] = pd.to_datetime(df["date"])
    return df


# Fighter A fights six times (oldest first): L to #12, W, W, L to #2, W, L to an unranked opponent.
# Only the last five decided bouts count, so the oldest loss (to #12) must be ignored.
# Fighter Z has two losses and nothing else; a draw and a no-contest must be skipped everywhere.
A_HISTORY = _bouts([
    (1, "2020-01-01", "A", "O1", 0.0, 99, 12),
    (2, "2020-06-01", "A", "O2", 1.0, 99, 99),
    (3, "2021-01-01", "O3", "A", 0.0, 50, 20),    # A listed second and won
    (4, "2021-06-01", "A", "O4", 0.0, 15, 2),
    (5, "2022-01-01", "A", "O5", 1.0, 10, 30),
    (6, "2022-06-01", "O6", "A", 1.0, np.nan, 9),  # loss to an opponent whose rank is unknown
    (7, "2022-07-01", "A", "O7", 0.5, 9, 9),       # draw, ignored
    (8, "2022-08-01", "A", "O8", np.nan, 9, 9),    # no contest, ignored
    (9, "2020-03-01", "Z", "O9", 0.0, 99, 0),      # loss to the champion
    (10, "2020-04-01", "Z", "O10", 0.0, 99, 99),
])


class TestHorizonWeight:
    def test_inclusive_upper_limits(self) -> None:
        assert horizon_weight(0.0, HORIZONS) == 1.0
        assert horizon_weight(3.0, HORIZONS) == 1.0
        assert horizon_weight(3.01, HORIZONS) == 0.6
        assert horizon_weight(5.0, HORIZONS) == 0.6
        assert horizon_weight(7.5, HORIZONS) == 0.3
        assert horizon_weight(15.0, HORIZONS) == 0.1

    def test_beyond_last_horizon_is_zero(self) -> None:
        assert horizon_weight(15.01, HORIZONS) == 0.0
        assert horizon_weight(40.0, HORIZONS) == 0.0

    def test_key_order_does_not_matter(self) -> None:
        shuffled = {15.0: 0.1, 3.0: 1.0, 10.0: 0.3, 5.0: 0.6}
        for age in (0.5, 3.0, 4.0, 9.9, 12.0, 20.0):
            assert horizon_weight(age, shuffled) == horizon_weight(age, HORIZONS)

    def test_accepts_yaml_integer_keys_once_cast_as_build_does(self) -> None:
        yaml_keys = {3: 1.0, 5: 0.6, 10: 0.3, 15: 0.1}
        hz = {float(k): v for k, v in yaml_keys.items()}
        assert horizon_weight(4.0, hz) == 0.6


class TestIdrScale:
    def test_median_maps_to_zero_and_interdecile_range_to_one(self) -> None:
        s = pd.Series(np.arange(11, dtype=float))        # 0..10: q10 = 1, q50 = 5, q90 = 9
        z = idr_scale(s)
        assert z.iloc[5] == pytest.approx(0.0)
        assert z.iloc[9] - z.iloc[1] == pytest.approx(1.0)
        assert z.iloc[10] == pytest.approx(5 / 8)
        assert z.index.equals(s.index)

    def test_constant_series_is_all_zero_not_nan(self) -> None:
        z = idr_scale(pd.Series([1500.0] * 6))
        assert np.isfinite(z).all() and (z == 0.0).all()

    def test_affine_invariance(self) -> None:
        s = pd.Series([1450.0, 1500.0, 1510.0, 1560.0, 1600.0, 1700.0, 1480.0])
        pd.testing.assert_series_equal(idr_scale(3 * s + 100), idr_scale(s))


class TestLastFive:
    def test_record_and_streak(self) -> None:
        lf = last_five(A_HISTORY)
        assert lf.loc["A", "last5"] == "3-2"      # W W L W L once the oldest loss drops out
        assert lf.loc["A", "streak"] == "L1"
        assert lf.loc["Z", "last5"] == "0-2"
        assert lf.loc["Z", "streak"] == "L2"

    def test_opponents_appear_with_their_own_records(self) -> None:
        lf = last_five(A_HISTORY)
        assert lf.loc["O1", "last5"] == "1-0" and lf.loc["O1", "streak"] == "W1"
        assert lf.loc["O3", "last5"] == "0-1"
        assert "O7" not in lf.index and "O8" not in lf.index     # draw and no-contest only

    def test_same_day_bouts_are_ordered_by_bout_id(self) -> None:
        same_day = _bouts([
            (2, "2024-01-01", "A", "B", 0.0, 99, 99),
            (1, "2024-01-01", "A", "C", 1.0, 99, 99),
        ])
        lf = last_five(same_day)
        assert lf.loc["A", "streak"] == "L1"     # bout 2 is the later one

    def test_streak_spans_more_than_five_bouts(self) -> None:
        rows = [(i, f"2020-{i:02d}-01", "A", f"O{i}", 1.0, 99, 99) for i in range(1, 8)]
        lf = last_five(_bouts(rows))
        assert lf.loc["A", "last5"] == "5-0"
        assert lf.loc["A", "streak"] == "W7"


TIERS = [[15, 0.30], [0, 0.05], [5, 0.10], [10, 0.20], [99, 0.40]]   # deliberately unsorted


class TestTieredFormPenalty:
    def test_costs_losses_by_opponent_rank_in_last_five_only(self) -> None:
        pen = tiered_form_penalty(A_HISTORY, TIERS, cap=10.0)
        # A: loss to #2 (0.10) + loss to an unknown rank, read as unranked (0.40); the loss to #12 is the sixth bout back
        assert pen["A"] == pytest.approx(0.50)
        # Z: loss to the champion (rank 0 -> 0.05) + loss to an unranked opponent (0.40)
        assert pen["Z"] == pytest.approx(0.45)

    def test_wins_cost_nothing_and_cap_applies(self) -> None:
        pen = tiered_form_penalty(A_HISTORY, TIERS, cap=0.3)
        assert pen["A"] == pytest.approx(0.3)
        assert pen["O1"] == 0.0 and pen["O4"] == 0.0      # both beat A, no losses on record
        assert pen["O2"] == pytest.approx(0.3)             # one loss to an unranked A, capped

    def test_rank_beyond_last_tier_costs_the_last_tier(self) -> None:
        short = [[0, 0.05], [10, 0.20]]
        pen = tiered_form_penalty(A_HISTORY, short, cap=10.0)
        assert pen["Z"] == pytest.approx(0.05 + 0.20)


class TestBadLossesLastFive:
    def test_counts_losses_to_opponents_outside_the_threshold(self) -> None:
        bad = bad_losses_last_five(A_HISTORY, rank_above=10)
        assert bad["A"] == 1        # the unknown-rank loss; the loss to #2 is not bad, the loss to #12 is too old
        assert bad["Z"] == 1        # unranked opponent, not the champion
        assert bad["O1"] == 0       # won its only bout
        assert bad["O2"] == 1       # lost to A, who was unranked (99) at the time

    def test_threshold_is_exclusive(self) -> None:
        rows = [(1, "2024-01-01", "A", "B", 0.0, 99, 10), (2, "2024-02-01", "A", "C", 0.0, 99, 11)]
        bad = bad_losses_last_five(_bouts(rows), rank_above=10)
        assert bad["A"] == 1


class TestMerge:
    BASE = {"weights": {"rating": 0.7, "quality_wins": 0.3}, "engine": {"k": 60, "n_new": 5}, "flag": False}

    def test_none_override_returns_an_equal_copy(self) -> None:
        out = _merge(self.BASE, None)
        assert out == self.BASE and out is not self.BASE

    def test_nested_override_keeps_sibling_keys(self) -> None:
        out = _merge(self.BASE, {"engine": {"k": 80}})
        assert out["engine"] == {"k": 80, "n_new": 5}
        assert out["weights"] == self.BASE["weights"]

    def test_new_keys_and_scalar_replacement(self) -> None:
        out = _merge(self.BASE, {"flag": True, "extra": {"a": 1}, "weights": "fixed"})
        assert out["flag"] is True and out["extra"] == {"a": 1} and out["weights"] == "fixed"

    def test_base_is_not_mutated(self) -> None:
        import copy
        before = copy.deepcopy(self.BASE)
        _merge(self.BASE, {"engine": {"k": 1}})
        assert self.BASE == before
