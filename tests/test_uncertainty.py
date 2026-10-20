"""Tests for the Glicko-1 rating deviation track (src/mmalab/uncertainty.py).

Textbook anchor: Glickman's worked example, a 1500/200 player who meets 1400/30 (win), 1550/100 (loss)
and 1700/300 (loss) in one rating period: g = 0.9955, 0.9531, 0.7242; E = 0.639, 0.432, 0.303;
d^2 = 53685.74; RD' = 151.4. The per-bout sequential update used here, with the player's rating held at
1500 and no inflation between the bouts, must pass through 175.22 and 158.20 and land on the same 151.4,
because precisions add: 1/RD'^2 = 1/RD^2 + sum_j 1/d_j^2.
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mmalab.uncertainty import (UncertaintyParams, band_positions, d_squared, expected, g, inflate, load_params,
                                rd_as_of, rd_track, rd_update)

ROOT = Path(__file__).resolve().parents[1]
Q = math.log(10.0) / 400.0
GLICKMAN = [(1400.0, 30.0), (1550.0, 100.0), (1700.0, 300.0)]


def _out(rows: list[tuple]) -> pd.DataFrame:
    """A minimal `out` frame: (date, bout_id, division, a, b, result_a, r_pre_a, r_pre_b)."""
    df = pd.DataFrame(rows, columns=["date", "bout_id", "division", "fighter_a", "fighter_b", "result_a", "r_pre_a", "r_pre_b"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _newcomer_rd(rd_start: float = 350.0) -> float:
    """Independent formula: RD after one bout between two debutants at equal ratings."""
    gg = 1.0 / math.sqrt(1.0 + 3.0 * Q * Q * rd_start ** 2 / math.pi ** 2)
    d2 = 1.0 / (Q * Q * gg * gg * 0.25)
    return math.sqrt(1.0 / (1.0 / rd_start ** 2 + 1.0 / d2))


# --------------------------------------------------------------------------- Glicko formulas

def test_textbook_pieces():
    assert g(30.0) == pytest.approx(0.9955, abs=5e-5)
    assert g(100.0) == pytest.approx(0.9531, abs=5e-5)
    assert g(300.0) == pytest.approx(0.7242, abs=5e-5)
    assert expected(1500.0, 1400.0, 30.0) == pytest.approx(0.639, abs=5e-4)
    assert expected(1500.0, 1550.0, 100.0) == pytest.approx(0.432, abs=5e-4)
    assert expected(1500.0, 1700.0, 300.0) == pytest.approx(0.303, abs=5e-4)
    period_d2 = 1.0 / sum(1.0 / d_squared(1500.0, r, rd) for r, rd in GLICKMAN)
    assert period_d2 == pytest.approx(53685.74, abs=0.01)
    assert math.sqrt(1.0 / (1.0 / 200.0 ** 2 + 1.0 / period_d2)) == pytest.approx(151.4, abs=0.05)


def test_sequential_update_matches_rating_period():
    rd, path = 200.0, []
    for r_opp, rd_opp in GLICKMAN:
        rd = rd_update(rd, 1500.0, r_opp, rd_opp, rd_min=0.0)
        path.append(rd)
    assert path == pytest.approx([175.22, 158.20, 151.40], abs=0.01)
    period_d2 = 1.0 / sum(1.0 / d_squared(1500.0, r, rd_) for r, rd_ in GLICKMAN)
    assert rd == pytest.approx(math.sqrt(1.0 / (1.0 / 200.0 ** 2 + 1.0 / period_d2)), abs=1e-9)


def test_update_is_symmetric_in_gap_and_uses_opponent_rd():
    # the same |gap| gives the same RD whichever side is favoured
    assert rd_update(200.0, 1500.0, 1600.0, 80.0, 0.0) == pytest.approx(rd_update(200.0, 1600.0, 1500.0, 80.0, 0.0))
    # a less certain opponent (larger RD) is a weaker measurement: RD shrinks less
    assert rd_update(200.0, 1500.0, 1500.0, 300.0, 0.0) > rd_update(200.0, 1500.0, 1500.0, 50.0, 0.0)
    # a lopsided bout carries less information than an even one
    assert rd_update(200.0, 1500.0, 1900.0, 50.0, 0.0) > rd_update(200.0, 1500.0, 1500.0, 50.0, 0.0)


# --------------------------------------------------------------------------- inflation cap and floor

def test_inflation_cap():
    assert inflate(60.0, 1.0, 100.0, 350.0) == pytest.approx(math.sqrt(60.0 ** 2 + 100.0 ** 2))
    assert inflate(60.0, 2.0, 100.0, 350.0) == pytest.approx(math.sqrt(60.0 ** 2 + 2.0 * 100.0 ** 2))
    assert inflate(60.0, 20.0, 100.0, 350.0) == 350.0           # capped at rd_start
    assert inflate(60.0, 0.0, 100.0, 350.0) == 60.0             # same-day bout: no inflation
    assert inflate(60.0, -1.0, 100.0, 350.0) == 60.0            # negative time is clipped
    assert inflate(60.0, 3.0, 0.0, 350.0) == 60.0               # c = 0: no inflation at all


def test_floor():
    free = rd_update(350.0, 1500.0, 1500.0, 350.0, rd_min=0.0)
    assert free == pytest.approx(_newcomer_rd(), abs=1e-9)
    assert free < 300.0
    assert rd_update(350.0, 1500.0, 1500.0, 350.0, rd_min=300.0) == 300.0
    assert rd_update(350.0, 1500.0, 1500.0, 350.0, rd_min=40.0) == pytest.approx(free)


def test_track_floor_binds_for_every_row():
    out = _out([("2020-01-01", 0, "Lightweight", "A", "B", 1.0, 1500.0, 1500.0),
                ("2020-06-01", 1, "Lightweight", "A", "C", 0.0, 1545.0, 1500.0),
                ("2021-01-01", 2, "Lightweight", "B", "C", 1.0, 1455.0, 1545.0)])
    tr = rd_track(out, UncertaintyParams(350.0, 300.0, 0.0))
    assert (tr["rd_post"] >= 300.0).all()
    assert (tr["rd_post"] == 300.0).all()                       # the formula gives < 300 everywhere here


# --------------------------------------------------------------------------- the track

def test_track_newcomers_nc_and_idle_clock():
    c, rd_start = 50.0, 350.0
    p = UncertaintyParams(rd_start, 40.0, c)
    out = _out([("2020-01-01", 0, "Lightweight", "A", "B", 1.0, 1500.0, 1500.0),
                ("2021-01-01", 1, "Lightweight", "A", "C", np.nan, 1545.0, 1500.0),    # no contest
                ("2022-01-01", 2, "Lightweight", "A", "D", 0.5, 1545.0, 1500.0)])      # draw
    before = out.copy(deep=True)
    tr = rd_track(out, p)
    pd.testing.assert_frame_equal(out, before)                  # read-only
    assert list(tr.columns[:4]) == ["fighter", "date", "bout_id", "division"]
    assert len(tr) == 6 and list(tr["fighter"]) == ["A", "B", "A", "C", "A", "D"]
    assert tr["date"].is_monotonic_increasing and tr["bout_id"].is_monotonic_increasing
    a = tr[tr["fighter"] == "A"].reset_index(drop=True)
    assert list(a["n_bout"]) == [1, 2, 3]                      # the NC counts as a bout
    # debut: rd_pre is rd_start, both newcomers shrink to the same textbook-derived value
    assert a.loc[0, "rd_pre"] == rd_start
    assert a.loc[0, "rd_post"] == pytest.approx(_newcomer_rd(rd_start), abs=1e-9)
    assert tr.loc[1, "rd_post"] == pytest.approx(a.loc[0, "rd_post"])
    # NC: inflated going in, carried out unchanged, not informative; the debuting opponent stays at rd_start
    years1 = (pd.Timestamp("2021-01-01") - pd.Timestamp("2020-01-01")).days / 365.25
    assert a.loc[1, "rd_pre"] == pytest.approx(math.sqrt(a.loc[0, "rd_post"] ** 2 + c * c * years1))
    assert a.loc[1, "rd_post"] == a.loc[1, "rd_pre"]
    assert not a.loc[1, "informative"]
    c_row = tr[tr["fighter"] == "C"].iloc[0]
    assert c_row["rd_pre"] == rd_start and c_row["rd_post"] == rd_start
    # the idle clock runs through the NC: the draw's rd_pre equals two years of inflation from bout 0
    years2 = (pd.Timestamp("2022-01-01") - pd.Timestamp("2020-01-01")).days / 365.25
    assert a.loc[2, "rd_pre"] == pytest.approx(math.sqrt(a.loc[0, "rd_post"] ** 2 + c * c * years2))
    # a draw is a measurement: the update is applied against the opponent's rd_pre
    assert a.loc[2, "informative"]
    assert a.loc[2, "rd_post"] == pytest.approx(rd_update(a.loc[2, "rd_pre"], 1545.0, 1500.0, rd_start, 40.0))
    assert a.loc[2, "rd_post"] < a.loc[2, "rd_pre"]


def test_track_draw_and_win_shrink_alike():
    win = rd_track(_out([("2020-01-01", 0, "Lightweight", "A", "B", 1.0, 1500.0, 1500.0)]), UncertaintyParams(350.0, 40.0, 0.0))
    draw = rd_track(_out([("2020-01-01", 0, "Lightweight", "A", "B", 0.5, 1500.0, 1500.0)]), UncertaintyParams(350.0, 40.0, 0.0))
    assert win["rd_post"].tolist() == pytest.approx(draw["rd_post"].tolist())


def test_track_inflation_is_capped_at_rd_start():
    out = _out([("2010-01-01", 0, "Lightweight", "A", "B", 1.0, 1500.0, 1500.0),
                ("2025-01-01", 1, "Lightweight", "A", "C", 1.0, 1545.0, 1500.0)])
    tr = rd_track(out, UncertaintyParams(350.0, 40.0, 100.0))
    a2 = tr[(tr["fighter"] == "A") & (tr["bout_id"] == 1)].iloc[0]
    assert a2["rd_pre"] == 350.0                                # fifteen years away: as uncertain as a debutant
    assert a2["rd_post"] == pytest.approx(rd_update(350.0, 1545.0, 1500.0, 350.0, 40.0))
    assert a2["rd_post"] == pytest.approx(290.57, abs=0.01)     # near the even-matchup debutant value of 290.23


def test_track_orders_by_date_not_input_order():
    rows = [("2021-01-01", 1, "Lightweight", "A", "C", 1.0, 1545.0, 1500.0),
            ("2020-01-01", 0, "Lightweight", "A", "B", 1.0, 1500.0, 1500.0)]
    tr = rd_track(_out(rows), UncertaintyParams(350.0, 40.0, 0.0))
    assert tr["bout_id"].tolist() == [0, 0, 1, 1]
    assert tr.loc[tr["fighter"] == "A", "n_bout"].tolist() == [1, 2]


# --------------------------------------------------------------------------- rd_as_of

def test_rd_as_of():
    c, rd_start = 50.0, 350.0
    p = UncertaintyParams(rd_start, 40.0, c)
    out = _out([("2020-01-01", 0, "Lightweight", "A", "B", 1.0, 1500.0, 1500.0),
                ("2021-01-01", 1, "Lightweight", "A", "C", 1.0, 1545.0, 1500.0)])
    tr = rd_track(out, p)
    last_a = tr[tr["fighter"] == "A"].iloc[-1]["rd_post"]
    last_b = tr[tr["fighter"] == "B"].iloc[-1]["rd_post"]
    two_years = pd.Timestamp("2023-01-01")
    rd = rd_as_of(tr, two_years, p)
    assert set(rd.index) == {"A", "B", "C"} and rd.name == "rd"
    ya = (two_years - pd.Timestamp("2021-01-01")).days / 365.25
    yb = (two_years - pd.Timestamp("2020-01-01")).days / 365.25
    assert rd["A"] == pytest.approx(math.sqrt(last_a ** 2 + c * c * ya))
    assert rd["B"] == pytest.approx(math.sqrt(last_b ** 2 + c * c * yb))
    assert rd["B"] > rd["A"]                                    # B has been away longer
    # on the day of the last bout nothing is added; before it nothing is subtracted
    assert rd_as_of(tr, "2021-01-01", p)["A"] == pytest.approx(last_a)
    assert rd_as_of(tr, "2020-06-01", p)["A"] == pytest.approx(last_a)
    # capped at rd_start far out, and untouched with c = 0
    assert rd_as_of(tr, "2080-01-01", p)["A"] == rd_start
    assert rd_as_of(tr, "2080-01-01", UncertaintyParams(rd_start, 40.0, 0.0))["A"] == pytest.approx(last_a)


# --------------------------------------------------------------------------- band positions

def test_band_positions():
    ratings = pd.Series({"p1": 1700.0, "p2": 1650.0, "p3": 1600.0, "p4": 1550.0, "p5": 1500.0, "q1": 1660.0, "q2": 1640.0})
    rd = pd.Series({"p1": 10.0, "p2": 60.0, "p3": 10.0, "p4": 60.0, "p5": 10.0, "q1": 30.0})   # q2 has no RD
    division = pd.Series({k: ("LW" if k.startswith("p") else "WW") for k in ratings.index})
    b = band_positions(ratings, rd, division, z=1.0)
    assert b.index.name == "fighter" and set(b.index) == set(ratings.index)
    p2 = b.loc["p2"]                                            # band [1590, 1710]: p1 and p3 inside
    assert (p2["n_tied"], p2["rank_rating"], p2["rank_best"], p2["rank_worst"], p2["band_span"]) == (2, 2, 1, 3, 3)
    p1 = b.loc["p1"]                                            # band [1690, 1710]: alone at the top
    assert (p1["n_tied"], p1["rank_best"], p1["rank_worst"], p1["band_span"]) == (0, 1, 1, 1)
    p4 = b.loc["p4"]                                            # band [1490, 1610]: p3 and p5 inside
    assert (p4["n_tied"], p4["rank_rating"], p4["rank_best"], p4["rank_worst"], p4["band_span"]) == (2, 4, 3, 5, 3)
    assert (b.loc["p5"]["rank_best"], b.loc["p5"]["rank_worst"]) == (5, 5)
    q1 = b.loc["q1"]                                            # the other division: only q2 counts, p* do not
    assert (q1["n_tied"], q1["rank_rating"], q1["rank_best"], q1["rank_worst"]) == (1, 1, 1, 2)
    assert np.isnan(b.loc["q2", "band_span"]) and b.loc["q2", "rank_rating"] == 2
    # z scales the band: at z = 0.1 nobody is tied with p2
    assert band_positions(ratings, rd, division, z=0.1).loc["p2", "n_tied"] == 0


def test_load_params_reads_config():
    p = load_params()
    assert p.rd_start == 350.0 and p.rd_min == 40.0 and 0.0 < p.c_per_year < p.rd_start


# --------------------------------------------------------------------------- the real data (read-only check)

@pytest.mark.skipif(not (ROOT / "data" / "processed" / "bouts_with_stats.csv").exists(), reason="processed data not present")
def test_track_leaves_engine_output_untouched_on_real_data():
    import yaml
    from mmalab.resume import ResumeParams, run_resume
    rc = yaml.safe_load((ROOT / "config" / "weights.yaml").read_text())["resume"]
    bouts = pd.read_csv(ROOT / "data" / "processed" / "bouts_with_stats.csv", parse_dates=["date"])
    out, hist = run_resume(bouts, ResumeParams(**rc["engine"]))
    out0, hist0 = out.copy(deep=True), hist.copy(deep=True)
    p = load_params()
    track = rd_track(out, p)
    rd = rd_as_of(track, out["date"].max() + pd.Timedelta(days=1), p)
    pd.testing.assert_frame_equal(out, out0)
    pd.testing.assert_frame_equal(hist, hist0)
    assert len(track) == 2 * len(out)                           # one row per fighter per bout, no-contests included
    bouts_per_fighter = pd.concat([out["fighter_a"], out["fighter_b"]]).value_counts()
    maxn = track.groupby("fighter")["n_bout"].max()
    assert (maxn == bouts_per_fighter.reindex(maxn.index)).all()
    assert (track["rd_post"] >= p.rd_min).all() and (track["rd_pre"] <= p.rd_start).all()
    nc = ~track["informative"]
    assert (track.loc[nc, "rd_pre"] == track.loc[nc, "rd_post"]).all()
    shrinks = track.loc[~nc & (track["rd_pre"] > p.rd_min), ["rd_pre", "rd_post"]]
    assert (shrinks["rd_post"] < shrinks["rd_pre"]).all()       # every measurement tightens the RD
    assert rd.between(p.rd_min, p.rd_start).all() and len(rd) == track["fighter"].nunique()
