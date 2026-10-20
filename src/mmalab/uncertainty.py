"""
uncertainty.py - Glicko-1 rating deviation (RD) for the resume rating.

A separate, additive track. It reads the pre-fight ratings the engine already wrote
into `out` (r_pre_a, r_pre_b) and never writes back: no rating and no rank changes,
v1.0 stays frozen. The RD says how well a fighter is measured, so a one-bout
newcomer (RD near 350) and a twenty-bout veteran (RD near 100) stop looking equally
certain on the board.

Glicko-1 (Glickman 1999), per bout instead of per rating period:
  q        = ln(10) / 400
  g(RD)    = 1 / sqrt(1 + 3 q^2 RD^2 / pi^2)
  E        = 1 / (1 + 10^(-g(RD_opp) (r - r_opp) / 400))
  d^2      = 1 / (q^2 g(RD_opp)^2 E (1 - E))
  RD_post  = max(sqrt(1 / (1 / RD_pre^2 + 1 / d^2)), rd_min)
  RD_pre   = min(sqrt(RD_prev_post^2 + c^2 years_idle), rd_start)   inflation since the last bout
The RD update does not depend on the result, so a draw is handled like any decided
bout (it is still a measurement). A no-contest carries no information: the row is
kept with rd_pre = rd_post and the idle clock runs through it.

Parameters live in config/uncertainty.yaml. `derive_c` reproduces c from the data
with Glicko's rule c = sqrt((rd_start^2 - rd_typical^2) / t_years), solved
self-consistently because the typical RD itself depends on c.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "uncertainty.yaml"
Q = math.log(10.0) / 400.0
TRACK_COLUMNS = ["fighter", "date", "bout_id", "division", "opponent", "n_bout",
                 "r_pre", "r_opp_pre", "rd_pre", "rd_post", "informative"]


@dataclass(frozen=True)
class UncertaintyParams:
    rd_start: float = 350.0     # a debutant's RD
    rd_min: float = 40.0        # floor on RD_post
    c_per_year: float = 0.0     # RD inflation per idle year (0 = none)

    def to_dict(self) -> dict:
        return asdict(self)


def load_params(path: Path | None = None) -> UncertaintyParams:
    """Read config/uncertainty.yaml (only the three parameter keys are used)."""
    data = yaml.safe_load((path or CFG).read_text()) or {}
    return UncertaintyParams(rd_start=float(data["rd_start"]), rd_min=float(data["rd_min"]),
                             c_per_year=float(data["c_per_year"]))


# ---------------------------------------------------------------------------
# Glicko-1 pieces (scalar or array)

def g(rd):
    """Glicko attenuation of an opponent's rating by his RD."""
    return 1.0 / np.sqrt(1.0 + 3.0 * Q * Q * np.square(rd) / (math.pi ** 2))


def expected(r, r_opp, rd_opp):
    """Expected score against an opponent of rating r_opp and deviation rd_opp."""
    return 1.0 / (1.0 + np.power(10.0, -g(rd_opp) * (r - r_opp) / 400.0))


def d_squared(r, r_opp, rd_opp):
    """Information in one bout, Glicko's d^2 (large = little information)."""
    e = expected(r, r_opp, rd_opp)
    return 1.0 / (Q * Q * np.square(g(rd_opp)) * e * (1.0 - e))


def rd_update(rd_pre: float, r: float, r_opp: float, rd_opp: float, rd_min: float) -> float:
    """RD after one bout. Result-independent, floored at rd_min."""
    post = math.sqrt(1.0 / (1.0 / rd_pre ** 2 + 1.0 / float(d_squared(r, r_opp, rd_opp))))
    return max(post, rd_min)


def inflate(rd: float, years: float, c: float, rd_start: float) -> float:
    """RD after `years` without a bout, capped at rd_start."""
    return min(math.sqrt(rd ** 2 + c ** 2 * max(years, 0.0)), rd_start)


# ---------------------------------------------------------------------------
# The track

def rd_track(out: pd.DataFrame, params: UncertaintyParams | None = None) -> pd.DataFrame:
    """One row per (fighter, bout) in chronological order, with rd_pre (after inflation for the
    idle time) and rd_post (after the Glicko update against the opponent's rd_pre). `out` is the
    first frame run_resume returns; it is only read."""
    p = params or load_params()
    cols = ["date", "bout_id", "division", "fighter_a", "fighter_b", "result_a", "r_pre_a", "r_pre_b"]
    df = out[cols].sort_values(["date", "bout_id"], kind="mergesort")
    last_rd: dict[str, float] = {}
    last_date: dict[str, pd.Timestamp] = {}
    n_bout: dict[str, int] = {}
    rows = []
    for x in df.itertuples(index=False):
        a, b = x.fighter_a, x.fighter_b
        pre = {}
        for f in (a, b):
            if f in last_rd:
                pre[f] = inflate(last_rd[f], (x.date - last_date[f]).days / 365.25, p.c_per_year, p.rd_start)
            else:
                pre[f] = p.rd_start
        informative = not pd.isna(x.result_a)
        if informative:
            post_a = rd_update(pre[a], x.r_pre_a, x.r_pre_b, pre[b], p.rd_min)
            post_b = rd_update(pre[b], x.r_pre_b, x.r_pre_a, pre[a], p.rd_min)
        else:
            post_a, post_b = pre[a], pre[b]
        for f, opp, r, r_opp, rd_post in ((a, b, x.r_pre_a, x.r_pre_b, post_a), (b, a, x.r_pre_b, x.r_pre_a, post_b)):
            n_bout[f] = n_bout.get(f, 0) + 1
            rows.append((f, x.date, x.bout_id, x.division, opp, n_bout[f], r, r_opp, pre[f], rd_post, informative))
            last_rd[f], last_date[f] = rd_post, x.date
    return pd.DataFrame(rows, columns=TRACK_COLUMNS)


def rd_as_of(track: pd.DataFrame, as_of, params: UncertaintyParams | None = None) -> pd.Series:
    """Each fighter's last rd_post inflated to `as_of`, capped at rd_start. Indexed by fighter."""
    p = params or load_params()
    as_of = pd.Timestamp(as_of)
    last = track.sort_values(["date", "bout_id"], kind="mergesort").groupby("fighter").tail(1).set_index("fighter")
    years = ((as_of - last["date"]).dt.days / 365.25).clip(lower=0.0)
    rd = np.minimum(np.sqrt(last["rd_post"] ** 2 + p.c_per_year ** 2 * years), p.rd_start)
    return rd.rename("rd")


def band_positions(board_ratings: pd.Series, rd: pd.Series, division: pd.Series, z: float = 1.0) -> pd.DataFrame:
    """Per fighter (index): how many fighters in the same division sit within +/- z RD of his rating
    (n_tied, self excluded) and the rating rank he would hold at rating + z RD (rank_best) and at
    rating - z RD (rank_worst). Ranks are by rating among the fighters passed in, 1 = highest;
    band_span = rank_worst - rank_best + 1 positions. Fighters without an RD get NaN."""
    df = pd.DataFrame({"rating": board_ratings.astype(float), "division": division.reindex(board_ratings.index)})
    df["rd"] = rd.reindex(df.index).astype(float)
    for c in ("lo", "hi", "rank_rating", "rank_best", "rank_worst", "n_tied", "band_span"):
        df[c] = np.nan
    for _, g_ in df.groupby("division", sort=False):
        r = g_["rating"].to_numpy()
        d = z * g_["rd"].to_numpy()
        lo, hi = r - d, r + d
        others = r[None, :]
        eye = np.eye(len(r), dtype=bool)
        df.loc[g_.index, "lo"], df.loc[g_.index, "hi"] = lo, hi
        df.loc[g_.index, "rank_rating"] = 1 + ((others > r[:, None]) & ~eye).sum(1)
        df.loc[g_.index, "rank_best"] = 1 + ((others > hi[:, None]) & ~eye).sum(1)
        df.loc[g_.index, "rank_worst"] = 1 + ((others > lo[:, None]) & ~eye).sum(1)
        df.loc[g_.index, "n_tied"] = ((others >= lo[:, None]) & (others <= hi[:, None]) & ~eye).sum(1)
    df["band_span"] = df["rank_worst"] - df["rank_best"] + 1
    missing = df["rd"].isna()
    df.loc[missing, ["lo", "hi", "rank_best", "rank_worst", "n_tied", "band_span"]] = np.nan
    df.index.name = "fighter"
    return df


def board_bands(out: pd.DataFrame, board: pd.DataFrame, as_of, params: UncertaintyParams | None = None,
                z: float = 1.0) -> pd.DataFrame:
    """Convenience for resume_board.build(): rd as of `as_of` plus the band columns for every board row,
    indexed like `board` (which needs fighter, rating and division columns)."""
    p = params or load_params()
    track = rd_track(out, p)
    rd = rd_as_of(track, as_of, p)
    ratings = pd.Series(board["rating"].to_numpy(), index=board["fighter"])
    divs = pd.Series(board["division"].to_numpy(), index=board["fighter"])
    bands = band_positions(ratings, rd, divs, z=z)
    cols = ["rd", "rank_best", "rank_worst", "n_tied", "band_span"]
    return bands.loc[board["fighter"], cols].set_axis(board.index)


# ---------------------------------------------------------------------------
# Calibration and validation helpers

def derive_c(out: pd.DataFrame, rd_start: float = 350.0, rd_min: float = 40.0, t_years: float = 5.0,
             n_bouts: int = 10, max_iter: int = 25, tol: float = 0.05) -> dict:
    """Glicko's rule c = sqrt((rd_start^2 - rd_typical^2) / t_years), with rd_typical the median rd_post at a
    fighter's n_bouts-th UFC bout. rd_typical depends on c, so iterate to the fixed point from c = 0; the
    path is returned so the first pass (no inflation) can be reported next to the converged value."""
    c, path, rd_typical = 0.0, [], float("nan")
    for _ in range(max_iter):
        track = rd_track(out, UncertaintyParams(rd_start, rd_min, c))
        rd_typical = float(track.loc[track["n_bout"] == n_bouts, "rd_post"].median())
        c_new = math.sqrt(max(rd_start ** 2 - rd_typical ** 2, 0.0) / t_years)
        path.append({"c_in": c, "rd_typical": rd_typical, "c_out": c_new})
        converged = abs(c_new - c) < tol
        c = c_new
        if converged:
            break
    return {"c_per_year": c, "rd_typical": rd_typical, "t_years": t_years, "n_bouts": n_bouts,
            "converged": converged, "path": path}


def balance_c(out: pd.DataFrame, rd_start: float = 350.0, rd_min: float = 40.0, veteran_bouts: int = 10) -> dict:
    """Information balance: the c at which, for a fighter on the median UFC cadence, the inflation between
    bouts equals the RD^2 removed by one typical bout for an established fighter (median rd_post at the
    last bout of fighters with veteran_bouts or more, no inflation). Regular activity then holds a
    veteran's RD at its information level and only idle time beyond the usual cadence widens it."""
    track = rd_track(out, UncertaintyParams(rd_start, rd_min, 0.0))
    last = track.groupby("fighter").tail(1)
    rd_v = float(last.loc[last["n_bout"] >= veteran_bouts, "rd_post"].median())
    inf = track[track["informative"]]
    d2 = float(np.median(d_squared(inf["r_pre"].to_numpy(), inf["r_opp_pre"].to_numpy(), inf["rd_pre"].to_numpy())))
    gap = float((track.sort_values(["fighter", "date", "bout_id"]).groupby("fighter")["date"].diff().dt.days / 365.25).median())
    removed = rd_v ** 2 - 1.0 / (1.0 / rd_v ** 2 + 1.0 / d2)
    return {"c_per_year": math.sqrt(removed / gap), "rd_veteran": rd_v, "d2_median": d2, "d_median": math.sqrt(d2),
            "cadence_years": gap, "rd2_removed_per_bout": removed}


def rd_by_experience(track: pd.DataFrame) -> pd.DataFrame:
    """RD at each fighter's last bout (rd_post, no inflation) by career UFC bouts: 1, 2-3, 4-9, 10+."""
    last = track.sort_values(["date", "bout_id"], kind="mergesort").groupby("fighter").tail(1)
    bucket = pd.cut(last["n_bout"], [0, 1, 3, 9, np.inf], labels=["1", "2-3", "4-9", "10+"])
    return (last.groupby(bucket, observed=True)["rd_post"]
            .agg(n="size", median="median", p10=lambda s: s.quantile(0.1), p90=lambda s: s.quantile(0.9)))


def calibration_table(out: pd.DataFrame, track: pd.DataFrame, since: str = "2015-01-01", bins: int = 8,
                      rd_scale: float = 1.0, seed: int = 7) -> pd.DataFrame:
    """Decided bouts since `since`, oriented so fighter a is the higher-rated one (exact ties broken by a
    seeded coin flip). Standardized gap z = (r_a - r_b) / sqrt(RD_a^2 + RD_b^2) is cut into `bins`
    equal-count bins; per bin: n, mean z, the plain Elo expectation (no RD), the Glicko expectation
    with g(sqrt(RD_a^2 + RD_b^2)), and the observed win rate of the higher-rated fighter with its
    standard error. `rd_scale` multiplies every RD, for a sensitivity read."""
    d = out.loc[out["result_a"].isin([0.0, 1.0]) & (out["date"] >= pd.Timestamp(since)),
                ["bout_id", "fighter_a", "fighter_b", "result_a", "r_pre_a", "r_pre_b"]].copy()
    key = track.set_index(["bout_id", "fighter"])["rd_pre"]
    d["rd_a"] = key.reindex(pd.MultiIndex.from_arrays([d["bout_id"], d["fighter_a"]])).to_numpy() * rd_scale
    d["rd_b"] = key.reindex(pd.MultiIndex.from_arrays([d["bout_id"], d["fighter_b"]])).to_numpy() * rd_scale
    flip = np.random.default_rng(seed).random(len(d)) < 0.5
    swap = (d["r_pre_a"] < d["r_pre_b"]) | ((d["r_pre_a"] == d["r_pre_b"]) & flip)
    ra = np.where(swap, d["r_pre_b"], d["r_pre_a"])
    rb = np.where(swap, d["r_pre_a"], d["r_pre_b"])
    rda = np.where(swap, d["rd_b"], d["rd_a"])
    rdb = np.where(swap, d["rd_a"], d["rd_b"])
    won = np.where(swap, d["result_a"] == 0.0, d["result_a"] == 1.0).astype(float)
    rd_c = np.sqrt(rda ** 2 + rdb ** 2)
    t = pd.DataFrame({"z": (ra - rb) / rd_c, "e_elo": 1.0 / (1.0 + 10.0 ** (-(ra - rb) / 400.0)),
                      "e_glicko": expected(ra, rb, rd_c), "won": won})
    t["bin"] = pd.qcut(t["z"].rank(method="first"), bins, labels=False) + 1
    tab = t.groupby("bin").agg(n=("won", "size"), z_lo=("z", "min"), z_hi=("z", "max"), z_mean=("z", "mean"),
                               e_elo=("e_elo", "mean"), e_glicko=("e_glicko", "mean"), win_rate=("won", "mean"))
    tab["se"] = np.sqrt(tab["win_rate"] * (1 - tab["win_rate"]) / tab["n"])
    return tab


def main() -> None:
    """Print the derivation of c and the validation tables for the current data."""
    from mmalab.resume import ResumeParams, run_resume
    cfg = yaml.safe_load((ROOT / "config" / "weights.yaml").read_text())["resume"]
    bouts = pd.read_csv(ROOT / "data" / "processed" / "bouts_with_stats.csv", parse_dates=["date"])
    out, _ = run_resume(bouts, ResumeParams(**cfg["engine"]))
    p = load_params()
    print(f"params (config/uncertainty.yaml): {p.to_dict()}")
    bc = balance_c(out, p.rd_start, p.rd_min)
    print(f"information balance: veteran RD {bc['rd_veteran']:.1f}, median d {bc['d_median']:.0f} per bout, "
          f"cadence {bc['cadence_years']:.3f} y, one bout removes {bc['rd2_removed_per_bout']:.0f} of RD^2 "
          f"-> c = {bc['c_per_year']:.2f}")
    dc = derive_c(out, p.rd_start, p.rd_min)
    print(f"Glicko rule (t = {dc['t_years']} y, rd_typical = median rd_post at bout {dc['n_bouts']}): "
          f"c = {dc['c_per_year']:.2f}, rd_typical = {dc['rd_typical']:.1f}, converged = {dc['converged']}")
    for step in dc["path"]:
        print(f"  c_in={step['c_in']:7.2f}  rd_typical={step['rd_typical']:6.1f}  c_out={step['c_out']:7.2f}")
    for label, c in (("config", p.c_per_year), ("Glicko rule", dc["c_per_year"])):
        track = rd_track(out, UncertaintyParams(p.rd_start, p.rd_min, c))
        print(f"\n=== c = {c:.2f} ({label}) ===")
        print("RD at the last bout by UFC bouts fought:")
        print(rd_by_experience(track).round(1).to_string())
        print("Calibration since 2015 (higher-rated fighter's win rate by standardized-gap bin):")
        tab = calibration_table(out, track)
        print(tab.round(3).to_string())
        se_mean = tab["se"].mean() / math.sqrt(len(tab))
        print(f"mean over bins of win_rate - e_glicko = {(tab['win_rate'] - tab['e_glicko']).mean():+.3f} "
              f"(positive = RDs too wide); win_rate - e_elo = {(tab['win_rate'] - tab['e_elo']).mean():+.3f}; "
              f"standard error of either mean about {se_mean:.3f}")


if __name__ == "__main__":
    main()
