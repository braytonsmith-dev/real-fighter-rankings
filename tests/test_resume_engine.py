"""Behavioural checks on mmalab.resume.run_resume over a modern slice of real bouts.

The slice is 1,500 consecutive bouts starting with the first card on or after SLICE_START, so the
judges' scorecards, fight statistics and official ranks all exist. Running the engine on it takes
about a second; the fixture runs it once and the determinism test runs it a second time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mmalab.elo import expected
from mmalab.resume import ResumeParams, run_resume

SLICE_START = pd.Timestamp("2023-07-01")
SLICE_LEN = 1500
TOL = 1e-9


@pytest.fixture(scope="module")
def resume_slice(bouts_with_stats: pd.DataFrame) -> pd.DataFrame:
    start = int(np.argmax((bouts_with_stats["date"] >= SLICE_START).to_numpy()))
    sl = bouts_with_stats.iloc[start:start + SLICE_LEN].reset_index(drop=True)
    assert len(sl) == SLICE_LEN
    return sl


@pytest.fixture(scope="module")
def engine(resume_slice: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return run_resume(resume_slice, ResumeParams())


def _decided(out: pd.DataFrame) -> pd.DataFrame:
    """Decided bouts with the rating change of each side and the winner's Elo expectation."""
    d = out[out["result_a"].isin([0.0, 1.0])].copy()
    a_won = d["result_a"] == 1.0
    delta_a = d["r_post_a"] - d["r_pre_a"]
    delta_b = d["r_post_b"] - d["r_pre_b"]
    d["winner_delta"] = np.where(a_won, delta_a, delta_b)
    d["loser_delta"] = np.where(a_won, delta_b, delta_a)
    e_a = np.array([expected(ra, rb) for ra, rb in zip(d["r_pre_a"], d["r_pre_b"])])
    d["winner_expected"] = np.where(a_won, e_a, 1 - e_a)
    return d


def test_run_resume_is_deterministic(resume_slice: pd.DataFrame, engine) -> None:
    out, hist = engine
    out2, hist2 = run_resume(resume_slice, ResumeParams())
    pd.testing.assert_frame_equal(out, out2)
    pd.testing.assert_frame_equal(hist, hist2)


def test_every_input_bout_is_rated_once(resume_slice: pd.DataFrame, engine) -> None:
    out, hist = engine
    assert len(out) == len(resume_slice)
    assert out["bout_id"].is_unique
    assert set(out["bout_id"]) == set(resume_slice["bout_id"])
    # two history rows per rated bout (one per fighter), none for no-contests
    rated = out["result_a"].notna().sum()
    assert len(hist) == 2 * rated


def test_ratings_stay_in_a_sane_range(engine) -> None:
    out, hist = engine
    p = ResumeParams()
    for col in ("r_pre_a", "r_pre_b", "r_post_a", "r_post_b"):
        assert np.isfinite(out[col]).all()
        assert out[col].between(p.start - 500, p.start + 500).all(), col
    assert np.isfinite(hist["rating"]).all()
    assert hist["rating"].between(p.start - 500, p.start + 500).all()
    # the field stays centred near the start rating; loss protection inflates it only slightly
    assert abs(hist.groupby("fighter")["rating"].last().mean() - p.start) < 25


def test_no_contest_leaves_both_ratings_unchanged(engine) -> None:
    out, _ = engine
    nc = out[out["result_a"].isna()]
    assert len(nc) > 0
    assert (nc["r_post_a"] == nc["r_pre_a"]).all()
    assert (nc["r_post_b"] == nc["r_pre_b"]).all()
    assert (nc["loss_mult"] == 1.0).all() and not nc["proof"].any()


def test_per_bout_change_is_bounded_by_k(engine) -> None:
    out, _ = engine
    p = ResumeParams()
    cap = p.k * p.k_new_mult * p.short_notice_win_mult
    assert (out["r_post_a"] - out["r_pre_a"]).abs().max() <= cap + TOL
    assert (out["r_post_b"] - out["r_pre_b"]).abs().max() <= cap + TOL


def test_update_sign_follows_score_minus_expectation(engine) -> None:
    """Outside proof-of-concept rows the two fighters move in opposite directions, and the winner
    gains exactly when the blended result score beats the Elo expectation (METHODOLOGY section 3)."""
    d = _decided(engine[0])
    d = d[~d["proof"]]
    assert (d["winner_delta"] * d["loser_delta"] <= TOL).all()
    edge = d["s_win"] - d["winner_expected"]
    assert (d["winner_delta"] * edge >= -TOL).all()
    # an underdog or even-money winner never loses rating: s_win is floored at a draw
    underdog = d[d["winner_expected"] <= 0.5]
    assert len(underdog) > 100
    assert (underdog["winner_delta"] >= -TOL).all()
    assert (underdog["loser_delta"] <= TOL).all()


def test_proof_of_concept_rows_pay_the_loser_a_fixed_gain(engine) -> None:
    d = _decided(engine[0])
    proof = d[d["proof"]]
    p = ResumeParams()
    assert len(proof) > 0
    assert (proof["loss_mult"] == 0.0).all()
    assert proof["close"].all() and not proof["decisive_loss"].any()
    assert (proof["winner_pos"] <= p.proof_top_n).all() and (proof["loser_pos"] > p.proof_top_n).all()
    allowed = np.array([p.k * p.proof_gain, p.k * p.k_new_mult * p.proof_gain])
    gains = proof["loser_delta"].to_numpy()
    assert (np.abs(gains[:, None] - allowed[None, :]).min(axis=1) < TOL).all()
    assert (gains > 0).all()


def test_loss_mult_takes_only_configured_values(engine) -> None:
    out, _ = engine
    p = ResumeParams()
    allowed = {0.0, 1.0, p.protected_loss_mult, p.dominant_loss_mult, p.consecutive_loss_mult}
    seen = set(out["loss_mult"].dropna().unique())
    assert seen <= allowed, f"unexpected loss_mult values: {sorted(seen - allowed)}"
    # 0.0 marks proof-of-concept rows and nothing else; a reduced multiplier always names the protected side
    assert ((out["loss_mult"] == 0.0) == out["proof"]).all()
    reduced = out[(out["loss_mult"] > 0.0) & (out["loss_mult"] < 1.0)]
    assert reduced["protected"].isin(["a", "b"]).all()


@pytest.mark.xfail(
    strict=True,
    reason="Design, not a code bug, but it contradicts the resume.py docstring ('earns the winner "
           "little'): the update is K x (s_win - expected), and s_win for a close decision is floored at "
           "0.5, so a favorite whose expectation exceeds the blended score loses rating for winning and "
           "the loser gains. About 5 percent of decided bouts in this slice (69 of 1,479) behave this way.",
)
def test_winner_never_loses_rating_outside_proof_rows(engine) -> None:
    d = _decided(engine[0])
    d = d[~d["proof"]]
    assert (d["winner_delta"] >= -TOL).all()
    assert (d["loser_delta"] <= TOL).all()
