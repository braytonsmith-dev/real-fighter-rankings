"""
decline.py - Individual decline and rise trajectories: a per-fighter age slope shrunk toward the population curve.

Why. The board tests (EXP-2026-10-20-09) and the literature (EXP-2026-10-20-13) agree that a rating lags a fighter who
is changing: favourites aged 35 or over win 45% of their bouts against 58 to 63% for younger favourites. Age in a vacuum
is a population statement. This module asks the individual question: given this fighter's own recent performances
relative to what his rating implied, is he running ahead of or behind his rating, and in which direction is he moving.

Outcome. Performance, not the win, as the aging-curve literature recommends (Berry, Reese and Larkey 1999; Vaci et al.
2019). For every fighter and decided bout the residual is

    r = s - e

where s is the engine's performance score for the fighter (0 to 1: finishes are 1 or 0, decisions blend the judges'
cards with the fight statistics, see resume.py) and e is the pre-fight expectation from the two ratings plus a corner
credit fitted on training rows (the red corner, the matchmakers' favourite, wins about 64% of bouts against 53%
expected by the rating alone; without the credit a fighter who is usually the favourite would look like a riser). The
rating update is K (s - e), so a run of same-signed residuals is exactly the drift the rating has not caught up with. A
second outcome, the statistical margin (dominance per minute, bout_stats.py) minus its rating-implied expectation, is
run as a check; the rating that defines e can be the prediction Elo (default) or the resume rating.

Model, in three parts, every quantity computed from information available before the bout:

    population curve   f(age): piecewise-linear regression of r on age (knots 27, 30, 33, 36), one curve per sex,
                       fitted on training years only
    individual level   L_i: recency-weighted mean of (r - f(age)) over the fighter's PRIOR bouts, shrunk toward 0
                       by lambda_level pseudo-bouts
    individual slope   b_i: recency-weighted regression slope of (r - f(age)) on age over the same bouts, shrunk
                       toward 0 by lambda_slope
    prediction         r_hat = f(age) + L_i + b_i (age - weighted mean prior age)

Recency weights are 0.5 ** (years before the bout / half_life). The three hyperparameters (lambda_level, lambda_slope,
half_life) are chosen each test year from the held-out performance of the years already tested, never from the test year.
One unit of residual corresponds to about 695 rating points of persistent lag (the slope of the Elo expectation curve
at e = 0.5 is ln(10) / 1600 per point), so a sustained residual of 0.05 is a rating about 35 points stale.

Tests, walk-forward by calendar year from 2016, training on 2011 onward:
  1. out-of-sample R squared of the realized residual: population curve alone, plus level, plus level and slope
  2. calibration: slope of realized adjusted residual on the individual prediction (1.0 is right, below 1 under-shrunk)
  3. log loss of the bout RESULT when the individual terms join the shadow model's features (paired event bootstrap)
  4. do fighters aged 33 or over in the lowest predicted quartile actually underperform and lose more next time
  5. (board_tune) concordance of the resume board when the index adjusts the rating, run separately

Outputs: outputs/decline_report.json and outputs/decline_index.csv (every fighter's indices as of the data date).

    PYTHONPATH=src python3 -m mmalab.decline [--rating elo|resume] [--outcome perf|margin] [--no-tune]
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from mmalab.resume import ResumeParams, run_resume
from mmalab.shadow import Logistic, features as shadow_features, metrics, paired_bootstrap

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"

KNOTS = (27.0, 30.0, 33.0, 36.0)
AGE_MIN, AGE_MAX = 18.0, 45.0                   # the population curve is evaluated inside the data's age range (99.9% of rows)
TUNE_FROM = pd.Timestamp("2011-01-01")
FIRST_TEST_YEAR = 2016
MIN_PRIOR = 3                                   # prior bouts needed before an individual term is used
POINTS_PER_RESIDUAL = 1600.0 / np.log(10.0)     # about 695 rating points per unit of persistent residual
DEFAULT_HP = {"lambda_level": 4.0, "lambda_slope": 60.0, "half_life": 2.5}
GRID = {"lambda_level": (4.0, 8.0, 16.0, 32.0, 64.0), "lambda_slope": (60.0, 200.0, 1000.0, 1e9), "half_life": (1.5, 2.5, 4.0, 1e6)}
# lambda_slope 1e9 switches the slope off (level only); half_life 1e6 is an unweighted mean.
SHADOW_BASE = ["elo_logit", "age_diff", "old_diff", "layoff_diff", "debut_diff", "exp_diff", "height_diff", "five_round", "elo_x_five"]


# ---------- residual table ----------

def residual_table(bouts: pd.DataFrame, rated: pd.DataFrame, fighters: pd.DataFrame, rating: str = "elo",
                   outcome: str = "perf") -> pd.DataFrame:
    """One row per fighter per decided bout with the pre-fight expectation and the performance residual.

    rating: "elo" uses the prediction model's Elo (bouts_rated.csv), "resume" the resume engine's rating.
    outcome: "perf" is s - e; "margin" is the dominance-per-minute differential minus its expectation, which is a
    linear function of the rating gap fitted later on training rows (column r is filled by `fit_margin`)."""
    out, _ = run_resume(bouts, ResumeParams())
    d = out[out["result_a"].isin([0.0, 1.0]) & out["s_a"].notna()].copy()
    if rating == "elo":
        ra = rated.set_index("bout_id")["elo_pre_a"].reindex(d["bout_id"]).to_numpy(dtype=float)
        rb = rated.set_index("bout_id")["elo_pre_b"].reindex(d["bout_id"]).to_numpy(dtype=float)
    else:
        ra, rb = d["r_pre_a"].to_numpy(dtype=float), d["r_pre_b"].to_numpy(dtype=float)
    s_a = d["s_a"].to_numpy(dtype=float)
    dom_a = d["dominance_a"].to_numpy(dtype=float)
    dob = pd.to_datetime(fighters.drop_duplicates("fighter").set_index("fighter")["dob"], errors="coerce")
    rows = []
    for side, other, sign in (("a", "b", 1.0), ("b", "a", -1.0)):
        res = d["result_a"].to_numpy(dtype=float) if side == "a" else 1.0 - d["result_a"].to_numpy(dtype=float)
        rows.append(pd.DataFrame({
            "bout_id": d["bout_id"].to_numpy(), "date": d["date"].to_numpy(), "event": d["event"].to_numpy(),
            "fighter": d[f"fighter_{side}"].to_numpy(), "opponent": d[f"fighter_{other}"].to_numpy(),
            "division": d["division"].to_numpy(), "side": side, "won": res,
            "s": s_a if side == "a" else 1.0 - s_a, "gap": sign * (ra - rb), "margin_raw": sign * dom_a}))
    t = pd.concat(rows).sort_values(["date", "bout_id", "side"]).reset_index(drop=True)
    t["age"] = (t["date"] - dob.reindex(t["fighter"]).to_numpy()).dt.days / 365.25
    t["female"] = t["division"].astype(str).str.startswith("Women").astype(int)
    t["e"] = expectation(t, 0.0)
    t["r"] = (t["s"] - t["e"]) if outcome == "perf" else np.nan
    t.attrs["rating"], t.attrs["outcome"] = rating, outcome
    return t


def expectation(t: pd.DataFrame, corner: float) -> np.ndarray:
    """Pre-fight expected score from the fighter's perspective, with `corner` rating points credited to the first-listed
    (red corner) fighter. The red corner is the matchmakers' favourite and wins about 64% of bouts against 53% expected
    by the rating alone, and that is pre-fight information the fighter-level residual must not absorb."""
    sign = np.where(t["side"].to_numpy() == "a", 1.0, -1.0)
    return 1.0 / (1.0 + 10 ** (-(t["gap"].to_numpy(dtype=float) + corner * sign) / 400.0))


def fit_corner(t: pd.DataFrame, train_mask: np.ndarray) -> float:
    """Corner credit (rating points) at which the red corner's mean performance score equals its mean expectation."""
    g = t[train_mask & (t["side"] == "a").to_numpy()]
    if len(g) < 100:
        return 0.0
    target = float(g["s"].mean())
    lo, hi = -400.0, 400.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if float(expectation(g, mid).mean()) < target:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 2)


def set_outcome(tt: pd.DataFrame, t_all: pd.DataFrame, train_mask: np.ndarray) -> tuple[pd.DataFrame, dict]:
    """Fill e and r on `tt` with expectation and margin parameters fitted on the training rows of `t_all` only."""
    corner = fit_corner(t_all, train_mask)
    tt = tt.copy()
    tt["e"] = expectation(tt, corner)
    fitted = {"corner_points": corner}
    if t_all.attrs.get("outcome") == "margin":
        beta = fit_margin(t_all, train_mask)
        tt["r"] = margin_residual(tt, beta)
        fitted["margin_slope_per_400"], fitted["margin_side_intercept"], fitted["margin_sd"] = (round(x, 4) for x in beta)
    else:
        tt["r"] = tt["s"] - tt["e"]
    tt.attrs.update(t_all.attrs)
    return tt, fitted


def fit_margin(t: pd.DataFrame, train_mask: np.ndarray) -> tuple[float, float, float]:
    """Expectation of the statistical margin as a linear function of the rating gap (training rows only).
    Returns (slope per 400 points, side-a intercept, residual sd). The side-b intercept is the negative by symmetry."""
    g = t[train_mask & t["margin_raw"].notna().to_numpy()]
    x = g["gap"].to_numpy(dtype=float) / 400.0
    sign = np.where(g["side"].to_numpy() == "a", 1.0, -1.0)
    X = np.column_stack([sign, x])
    y = g["margin_raw"].to_numpy(dtype=float)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    sd = float(np.std(y - X @ beta)) or 1.0
    return float(beta[1]), float(beta[0]), sd


def margin_residual(t: pd.DataFrame, beta: tuple[float, float, float]) -> np.ndarray:
    slope, a_int, sd = beta
    sign = np.where(t["side"].to_numpy() == "a", 1.0, -1.0)
    return (t["margin_raw"].to_numpy(dtype=float) - (a_int * sign + slope * t["gap"].to_numpy(dtype=float) / 400.0)) / sd


# ---------- fighter groups (as of the bout, from career_stats.bout_features) ----------

GROUPS = {
    "style": "fighting style as of the bout (career_stats thresholds): striker, wrestler, mixed",
    "debut": "age at UFC debut: early (under 25), standard (25 to 28), late (29 or over)",
    "weight": "weight band: light (flyweight to featherweight), middle (lightweight, welterweight), heavy (middleweight and up)",
    "tenure": "UFC tenure at the bout: under 4 years or 4 years and over",
    "chin": "knockout losses in the previous three years: none or at least one",
}
LIGHT = {"Flyweight", "Bantamweight", "Featherweight", "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight", "Women's Featherweight"}
MIDDLE = {"Lightweight", "Welterweight"}
HEAVY = {"Middleweight", "Light Heavyweight", "Heavyweight"}


def attach_groups(t: pd.DataFrame, bout_feats: pd.DataFrame) -> pd.DataFrame:
    """Add the GROUPS columns to the residual table, each taken as of the bout from the fighter's own side."""
    t = t.copy()
    bf = bout_feats.set_index("bout_id") if "bout_id" in bout_feats.columns else bout_feats
    out = {k: np.full(len(t), "unknown", dtype=object) for k in GROUPS}
    for side in ("a", "b"):
        m = (t["side"] == side).to_numpy()
        rows = bf.reindex(t.loc[m, "bout_id"])
        style = rows[f"style_{side}"].astype(str).to_numpy()
        out["style"][m] = np.where(np.isin(style, ["striker", "wrestler", "mixed"]), style, "unknown")
        debut = (rows[f"age_{side}"] - rows[f"ufc_years_{side}"]).to_numpy(dtype=float)
        out["debut"][m] = np.select([np.isnan(debut), debut < 25, debut < 29], ["unknown", "early", "standard"], "late")
        tenure = rows[f"ufc_years_{side}"].to_numpy(dtype=float)
        out["tenure"][m] = np.select([np.isnan(tenure), tenure < 4], ["unknown", "under 4 years"], "4 years and over")
        ko3 = rows[f"ko_losses_3y_{side}"].to_numpy(dtype=float)
        out["chin"][m] = np.select([np.isnan(ko3), ko3 >= 1], ["unknown", "KO loss in 3 years"], "no KO loss in 3 years")
    div = t["division"].astype(str)
    out["weight"] = np.select([div.isin(LIGHT), div.isin(MIDDLE), div.isin(HEAVY)], ["light", "middle", "heavy"], "unknown")
    for k, v in out.items():
        t[k] = v
    return t


# ---------- population curve ----------

def hinge_design(age: np.ndarray) -> np.ndarray:
    cols = [np.ones_like(age), age - 30.0]
    for k in KNOTS:
        cols.append(np.maximum(0.0, age - k))
    return np.column_stack(cols)


def _solve_curve(g: pd.DataFrame) -> np.ndarray:
    X = hinge_design(g["age"].to_numpy(dtype=float))
    y = g["r"].to_numpy(dtype=float)
    reg = np.diag([0.0, 1.0] + [10.0] * len(KNOTS))
    return np.linalg.solve(X.T @ X + reg, X.T @ y)


def fit_population(train: pd.DataFrame, group_col: str | None = None, min_group: int = 300) -> dict:
    """Piecewise-linear regression of r on age, by sex; a light ridge on the hinge terms keeps the solve stable.
    With `group_col`, one curve per (sex, group) where the group has at least `min_group` rows, else the sex curve."""
    coefs = {}
    both = train[train["age"].notna() & train["r"].notna()]
    for sex in (0, 1):
        g = both[both["female"] == sex]
        if len(g) < 200:
            g = both
        coefs[sex] = _solve_curve(g)
        if group_col is not None:
            for grp, gg in g.groupby(group_col):
                if grp != "unknown" and len(gg) >= min_group:
                    coefs[(sex, grp)] = _solve_curve(gg)
    coefs["group_col"] = group_col
    return coefs


def population_curve(age: np.ndarray, female: np.ndarray, coefs: dict, group: np.ndarray | None = None) -> np.ndarray:
    """f(age) by sex (and group, when the curve set has one for it); 0 where the age is unknown."""
    age = np.asarray(age, dtype=float)
    female = np.asarray(female)
    f = np.zeros(len(age))
    ok = ~np.isnan(age)
    X = hinge_design(np.clip(np.where(ok, age, 30.0), AGE_MIN, AGE_MAX))      # no extrapolation beyond the data's age range
    for sex in (0, 1):
        m = ok & (female == sex)
        f[m] = X[m] @ coefs[sex]
        if group is not None and coefs.get("group_col") is not None:
            group = np.asarray(group).astype(str)
            for grp in np.unique(group[m]):
                if (sex, grp) in coefs:
                    mg = m & (group == grp)
                    f[mg] = X[mg] @ coefs[(sex, grp)]
    return f


def _group_values(t: pd.DataFrame, coefs: dict) -> np.ndarray | None:
    gc = coefs.get("group_col")
    return t[gc].to_numpy() if gc is not None and gc in t.columns else None


# ---------- individual terms (prior bouts only, vectorised with weighted cumulative sums) ----------

def individual_terms(t: pd.DataFrame, coefs: dict[int, np.ndarray], hp: dict | None = None) -> pd.DataFrame:
    """For every row: the fighter's shrunken level and slope from his PRIOR bouts only, and the implied prediction.

    Weights are 0.5 ** (years before this bout / half_life). Writing w_j = u_j / u_k with u = 2 ** (t / half_life)
    turns every weighted sum into a cumulative sum, so the whole table is done in a few vector operations.
    The level uses every prior decided bout; the slope uses the prior bouts whose age is known."""
    hp = {**DEFAULT_HP, **(hp or {})}
    t = t.sort_values(["fighter", "date", "bout_id"]).copy()
    t["pop_pred"] = population_curve(t["age"].to_numpy(), t["female"].to_numpy(), coefs, _group_values(t, coefs))
    t["adj"] = t["r"] - t["pop_pred"]
    g = t.groupby("fighter", sort=False)
    t0 = g["date"].transform("min")
    yrs = (t["date"] - t0).dt.days.to_numpy(dtype=float) / 365.25
    u = 2.0 ** (yrs / hp["half_life"])
    has_y = t["adj"].notna().to_numpy()
    has_a = has_y & t["age"].notna().to_numpy()
    y = np.nan_to_num(t["adj"].to_numpy(dtype=float))
    a = np.nan_to_num(t["age"].to_numpy(dtype=float))

    def prior_sum(x: np.ndarray) -> np.ndarray:
        return pd.Series(x, index=t.index).groupby(t["fighter"], sort=False).cumsum().to_numpy() - x

    S_u = prior_sum(u * has_y); S_uy = prior_sum(u * y * has_y); N = prior_sum(has_y.astype(float))
    Sa_u = prior_sum(u * has_a); Sa_ua = prior_sum(u * a * has_a); Sa_uy = prior_sum(u * y * has_a)
    Sa_uaa = prior_sum(u * a * a * has_a); Sa_uay = prior_sum(u * a * y * has_a); Na = prior_sum(has_a.astype(float))
    with np.errstate(divide="ignore", invalid="ignore"):
        W = S_u / u                                   # total weight of prior bouts, in this bout's units
        level = (S_uy / u) / (W + hp["lambda_level"])
        Wa = Sa_u / u
        abar = np.where(Wa > 0, (Sa_ua / u) / np.where(Wa > 0, Wa, 1.0), np.nan)
        # weighted covariance and variance of age with the adjusted residual, around the shrunken level
        cov = (Sa_uay - level * Sa_ua - abar * Sa_uy + abar * level * Sa_u) / u
        var = (Sa_uaa / u) - abar ** 2 * Wa
        slope = np.where(Wa > 0, cov / (np.where(Wa > 0, var, 1.0) + hp["lambda_slope"]), 0.0)
    usable = N >= MIN_PRIOR
    slope_ok = usable & (Na >= MIN_PRIOR) & t["age"].notna().to_numpy()
    t["n_prior"] = N.astype(int)
    t["ind_level"] = np.where(usable, level, 0.0)
    t["ind_slope"] = np.where(slope_ok, slope, 0.0)
    t["prior_mean_age"] = np.where(slope_ok, abar, np.nan)
    t["ind_pred"] = t["ind_level"] + np.where(slope_ok, t["ind_slope"] * (a - np.nan_to_num(abar)), 0.0)
    t["pred"] = t["pop_pred"] + t["ind_pred"]
    return t.sort_values(["date", "bout_id", "side"])


def individual_terms_reference(t: pd.DataFrame, coefs: dict[int, np.ndarray], hp: dict | None = None) -> pd.DataFrame:
    """Plain-loop version of individual_terms, kept for the test suite."""
    hp = {**DEFAULT_HP, **(hp or {})}
    t = t.sort_values(["date", "bout_id", "side"]).copy()
    t["pop_pred"] = population_curve(t["age"].to_numpy(), t["female"].to_numpy(), coefs, _group_values(t, coefs))
    t["adj"] = t["r"] - t["pop_pred"]
    level = np.zeros(len(t)); slope = np.zeros(len(t)); ind = np.zeros(len(t)); n_prior = np.zeros(len(t), dtype=int)
    for _, idx in t.groupby("fighter").indices.items():
        idx = np.sort(idx)
        dates, ages, adj = t["date"].to_numpy()[idx], t["age"].to_numpy(dtype=float)[idx], t["adj"].to_numpy(dtype=float)[idx]
        for k in range(len(idx)):
            prior = np.arange(k)
            has_y = ~np.isnan(adj[prior])
            n_prior[idx[k]] = int(has_y.sum())
            if has_y.sum() < MIN_PRIOR:
                continue
            w = 0.5 ** (((dates[k] - dates[prior]).astype("timedelta64[D]").astype(float) / 365.25) / hp["half_life"])
            L = float(np.sum((w * adj[prior])[has_y]) / (np.sum(w[has_y]) + hp["lambda_level"]))
            level[idx[k]] = L
            has_a = has_y & ~np.isnan(ages[prior])
            if has_a.sum() >= MIN_PRIOR and not np.isnan(ages[k]):
                wa, aa, yy = w[has_a], ages[prior][has_a], adj[prior][has_a]
                abar = float(np.sum(wa * aa) / np.sum(wa))
                cov = float(np.sum(wa * (aa - abar) * (yy - L)))
                var = float(np.sum(wa * (aa - abar) ** 2))
                b = cov / (var + hp["lambda_slope"])
                slope[idx[k]] = b
                ind[idx[k]] = L + b * (ages[k] - abar)
            else:
                ind[idx[k]] = L
    t["n_prior"], t["ind_level"], t["ind_slope"], t["ind_pred"] = n_prior, level, slope, ind
    t["pred"] = t["pop_pred"] + t["ind_pred"]
    return t


# ---------- evaluation ----------

def r2(y: np.ndarray, yhat: np.ndarray) -> float:
    ss = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - float(np.sum((y - yhat) ** 2)) / ss if ss > 0 else float("nan")


def heldout_year(t: pd.DataFrame, yr: int, hp: dict, group_col: str | None = None) -> pd.DataFrame:
    """Rows of test year `yr` with population and individual predictions built from information before each bout.
    The population curve (and the margin expectation) use training rows 2011 to yr-1; individual terms use each
    fighter's own earlier bouts, including those before 2011 and earlier in the test year."""
    years = t["date"].dt.year.to_numpy()
    upto = years <= yr
    train_mask = (years < yr) & (t["date"] >= TUNE_FROM).to_numpy()
    tt, fitted = set_outcome(t[upto], t, train_mask)
    coefs = fit_population(tt[train_mask[upto]], group_col)
    tt = individual_terms(tt, coefs, hp)
    te = tt[tt["date"].dt.year == yr].copy()
    te.attrs["fitted"] = fitted
    return te


def score_rows(te: pd.DataFrame) -> dict:
    y = te["r"].to_numpy(dtype=float)
    has = te["n_prior"].to_numpy() >= MIN_PRIOR
    out = {"rows": int(len(te)), "rows_with_terms": int(has.sum()),
           "r2_population": round(r2(y, te["pop_pred"].to_numpy()), 4),
           "r2_plus_level": round(r2(y, (te["pop_pred"] + te["ind_level"]).to_numpy()), 4),
           "r2_plus_level_and_slope": round(r2(y, te["pred"].to_numpy()), 4)}
    if has.sum() > 30:
        adj, ind = y[has] - te["pop_pred"].to_numpy()[has], te["ind_pred"].to_numpy()[has]
        out["corr_individual_vs_realized"] = round(float(np.corrcoef(ind, adj)[0, 1]), 4)
        out["calibration_slope"] = round(float(np.sum(ind * adj) / max(np.sum(ind * ind), 1e-12)), 3)
        out["mse_gain_from_individual"] = round(float(np.mean(adj ** 2) - np.mean((adj - ind) ** 2)), 5)
    return out


def walk_forward(t: pd.DataFrame, tune: bool = True, verbose: bool = True, group_col: str | None = None) -> tuple[list[dict], pd.DataFrame, list[dict]]:
    """Held-out predictions for every test year. With tune=True the hyperparameters for year Y are the grid point
    with the largest cumulative held-out MSE gain over the years already tested (the default for the first year)."""
    years = sorted(int(y) for y in t["date"].dt.year.unique() if y >= FIRST_TEST_YEAR)
    combos = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())] if tune else [DEFAULT_HP]
    per_combo_gain = {i: [] for i in range(len(combos))}
    held, per_year, chosen = [], [], []
    for yr in years:
        cache = {i: heldout_year(t, yr, hp, group_col) for i, hp in enumerate(combos)}
        if tune and chosen:
            cum = {i: float(np.sum(per_combo_gain[i])) for i in per_combo_gain}
            best = max(cum, key=cum.get)
        else:
            best = combos.index(DEFAULT_HP) if DEFAULT_HP in combos else 0
        te = cache[best].copy()
        for i in range(len(combos)):
            te_i = cache[i]
            has = te_i["n_prior"].to_numpy() >= MIN_PRIOR
            adj = te_i["r"].to_numpy(dtype=float)[has] - te_i["pop_pred"].to_numpy()[has]
            ind = te_i["ind_pred"].to_numpy()[has]
            per_combo_gain[i].append(float(np.sum(adj ** 2) - np.sum((adj - ind) ** 2)))   # summed, so years weigh by size
        row = {"year": yr, "hp": combos[best], "fitted": te.attrs.get("fitted"), **score_rows(te)}
        per_year.append(row)
        chosen.append({"year": yr, **combos[best]})
        te["year"] = yr
        held.append(te)
        if verbose:
            print(json.dumps(row), flush=True)
    return per_year, pd.concat(held, ignore_index=True), chosen


def result_test(held: pd.DataFrame, rated: pd.DataFrame, fighters: pd.DataFrame) -> dict:
    """Does the individual term improve the prediction of the RESULT beyond the shadow features (walk-forward)?"""
    f = shadow_features(rated, fighters, corner_adv=0.0)
    f["elo_logit"] = np.log(np.clip(f["p_elo"], 1e-4, 1 - 1e-4) / (1 - np.clip(f["p_elo"], 1e-4, 1 - 1e-4)))
    f["event"] = rated.set_index("bout_id")["event"].reindex(f.index).to_numpy()
    for side in ("a", "b"):
        h = held[held["side"] == side].set_index("bout_id")
        for c in ("ind_pred", "pop_pred", "ind_level"):
            f[f"{c}_{side}"] = h[c].reindex(f.index).to_numpy(dtype=float)
    for c in ("ind_pred", "pop_pred", "ind_level"):
        f[f"{c}_diff"] = f[f"{c}_a"].fillna(0.0) - f[f"{c}_b"].fillna(0.0)
    f = f[f["y"].isin([0.0, 1.0]) & f["ind_pred_a"].notna() & f["ind_pred_b"].notna()].copy()
    sets = {"M1 shadow": SHADOW_BASE,
            "M1 + population curve": SHADOW_BASE + ["pop_pred_diff"],
            "M1 + population + level": SHADOW_BASE + ["pop_pred_diff", "ind_level_diff"],
            "M1 + population + level and slope": SHADOW_BASE + ["pop_pred_diff", "ind_pred_diff"]}
    years = f["date"].dt.year.to_numpy()
    y = f["y"].to_numpy(dtype=float)
    ev = f["event"].astype(str).to_numpy() + "|" + f["date"].dt.strftime("%Y-%m-%d").to_numpy()
    preds = {}
    for name, cols in sets.items():
        p = np.full(len(f), np.nan)
        for yr in range(FIRST_TEST_YEAR + 1, int(years.max()) + 1):   # the logistic layer trains on held-out years only
            tr, te = years < yr, years == yr
            if tr.sum() < 300 or te.sum() == 0:
                continue
            p[te] = Logistic(cols).fit(f[tr], l2=4.0).predict(f[te])
        preds[name] = p
    m = ~np.isnan(preds["M1 shadow"])
    out = {"bouts": int(m.sum()), "window": [str(f["date"][m].min().date()), str(f["date"][m].max().date())],
           "note": "logistic layer trained only on bouts whose individual terms were themselves held out, so from 2017"}
    ll = {}
    for name, p in preds.items():
        pc = np.clip(p[m], 1e-6, 1 - 1e-6)
        ll[name] = -(y[m] * np.log(pc) + (1 - y[m]) * np.log(1 - pc))
        out[name] = metrics(y[m], pc)
    for name in list(sets)[1:]:
        d = ll["M1 shadow"] - ll[name]
        out[f"gain: {name} over M1"] = {"delta_log_loss": round(float(d.mean()), 4), "ci95_event_block_bootstrap": paired_bootstrap(d, ev[m])}
    old = (f["old_diff"] != 0).to_numpy()[m]
    out["bouts_with_a_fighter_33_or_over"] = {"bouts": int(old.sum()), "note": "approximated by a non-zero over-33 age difference"}
    for name, p in preds.items():
        out["bouts_with_a_fighter_33_or_over"][name] = metrics(y[m][old], np.clip(p[m][old], 1e-6, 1 - 1e-6))
    return out


AGE_BUCKETS = [17, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 50]


def heldout_by_age(held: pd.DataFrame) -> list[dict]:
    """Realized held-out residual, population prediction, win rate and expectation by age bucket: the rating's age
    bias as it actually showed up out of sample, next to the curve that predicted it."""
    h = held[held["age"].notna()].copy()
    h["bucket"] = pd.cut(h["age"], AGE_BUCKETS)
    rows = []
    for b, g in h.groupby("bucket", observed=True):
        rows.append({"ages": f"{int(b.left)} to {int(b.right)}", "n": int(len(g)), "mean_residual": round(float(g["r"].mean()), 4),
                     "population_curve": round(float(g["pop_pred"].mean()), 4), "win_rate": round(float(g["won"].mean()), 3),
                     "mean_expectation": round(float(g["e"].mean()), 3),
                     "rating_points_stale": round(float(g["r"].mean()) * POINTS_PER_RESIDUAL, 0)})
    return rows


def decliner_test(held: pd.DataFrame) -> dict:
    """Among held-out rows with individual terms and age 33 or over: do the lowest predicted fighters underperform?"""
    h = held[(held["n_prior"] >= MIN_PRIOR) & (held["age"] >= 33)].copy()
    if len(h) < 100:
        return {"rows_33_plus": int(len(h))}
    q = h["ind_pred"].quantile([0.25, 0.75])

    def block(g: pd.DataFrame) -> dict:
        return {"n": int(len(g)), "mean_residual": round(float(g["r"].mean()), 4), "mean_population_curve": round(float(g["pop_pred"].mean()), 4),
                "mean_individual_prediction": round(float(g["ind_pred"].mean()), 4), "win_rate": round(float(g["won"].mean()), 4),
                "mean_expectation": round(float(g["e"].mean()), 4), "wins_minus_expected_per_100": round(100 * float(g["won"].mean() - g["e"].mean()), 1)}
    return {"rows_33_plus": int(len(h)), "lowest_quartile_of_individual_prediction": block(h[h["ind_pred"] <= q[0.25]]),
            "middle_half": block(h[(h["ind_pred"] > q[0.25]) & (h["ind_pred"] < q[0.75])]),
            "highest_quartile": block(h[h["ind_pred"] >= q[0.75]]), "all_33_plus": block(h)}


# ---------- as-of index for the profile pages and the board test ----------

def index_as_of(t: pd.DataFrame, as_of: pd.Timestamp, hp: dict | None = None, coefs: dict | None = None,
                group_col: str | None = None) -> pd.DataFrame:
    """Every fighter's population expectation, individual level and slope as of `as_of`, from bouts before it only.
    The population curve is fitted on bouts from 2011 to the day before `as_of` unless `coefs` is given."""
    hp = {**DEFAULT_HP, **(hp or {})}
    as_of = pd.Timestamp(as_of)
    before = (t["date"] < as_of).to_numpy()
    prior, _ = set_outcome(t[before], t, before & (t["date"] >= TUNE_FROM).to_numpy())
    if coefs is None:
        coefs = fit_population(prior[prior["date"] >= TUNE_FROM], group_col)
    # one synthetic row per fighter dated as_of, so the vectorised prior-bout sums give the as-of terms
    last = prior.sort_values("date").groupby("fighter").tail(1)
    dob_age = last["age"] + (as_of - last["date"]).dt.days / 365.25
    probe = pd.DataFrame({"bout_id": -1, "date": as_of, "event": "", "fighter": last["fighter"].to_numpy(), "opponent": "",
                          "division": last["division"].to_numpy(), "side": "a", "won": np.nan, "s": np.nan, "gap": 0.0,
                          "margin_raw": np.nan, "age": dob_age.to_numpy(), "female": last["female"].to_numpy(), "e": np.nan, "r": np.nan})
    for k in GROUPS:
        if k in last.columns:
            probe[k] = last[k].to_numpy()          # the fighter's group as of his last bout
    both = pd.concat([prior, probe], ignore_index=True)
    terms = individual_terms(both, coefs, hp)
    idx = terms[terms["bout_id"] == -1].copy()
    idx = idx[idx["n_prior"] >= MIN_PRIOR]
    out = pd.DataFrame({"fighter": idx["fighter"].to_numpy(), "as_of": as_of.date().isoformat(), "age": idx["age"].round(1).to_numpy(),
                        "female": idx["female"].astype(int).to_numpy(),
                        "bouts_used": idx["n_prior"].to_numpy(), "population_expectation": idx["pop_pred"].round(4).to_numpy(),
                        "individual_level": idx["ind_level"].round(4).to_numpy(), "individual_slope_per_year": idx["ind_slope"].round(4).to_numpy(),
                        "individual_prediction": idx["ind_pred"].round(4).to_numpy(), "total_prediction": idx["pred"].round(4).to_numpy()})
    out["rating_points_equivalent"] = (out["total_prediction"] * POINTS_PER_RESIDUAL).round(1)
    out["last_bout"] = last.set_index("fighter")["date"].reindex(out["fighter"]).dt.date.astype(str).to_numpy()
    return out.sort_values("total_prediction").reset_index(drop=True)


# ---------- who declines faster: the population curve by fighter group ----------

CURVE_AGES = (24, 27, 30, 33, 35, 37, 40)


def stratified_report(full: pd.DataFrame, reps: int = 2000, seed: int = 5) -> dict:
    """Descriptive (all 2011+ men's rows, in sample): the population curve fitted within each group of every GROUPS
    column, its value at CURVE_AGES, the age at which it crosses zero, and an event-block bootstrap interval for the
    difference between the first two listed groups at 35 (striker minus wrestler, early minus late debut, and so on)."""
    men = full[(full["date"] >= TUNE_FROM) & (full["female"] == 0) & full["age"].notna() & full["r"].notna()].copy()
    ev = (men["event"].astype(str) + "|" + men["date"].dt.strftime("%Y-%m-%d")).to_numpy()
    ev_ids, inv = np.unique(ev, return_inverse=True)
    ages = np.array(CURVE_AGES, dtype=float)
    X = hinge_design(ages)
    rng = np.random.default_rng(seed)
    out = {"basis": f"{len(men)} men's fighter-bouts 2011 to {men['date'].max().date()}, residual outcome as in the main run, in sample",
           "ages": list(CURVE_AGES), "groups": {}}
    contrasts = {"style": ("striker", "wrestler"), "debut": ("early", "late"), "weight": ("light", "heavy"),
                 "tenure": ("under 4 years", "4 years and over"), "chin": ("no KO loss in 3 years", "KO loss in 3 years")}
    for col in GROUPS:
        if col not in men.columns:
            continue
        rows = {}
        for grp, g in men.groupby(col):
            if grp == "unknown" or len(g) < 300:
                continue
            c = _solve_curve(g)
            vals = X @ c
            lo, hi = (float(x) for x in g["age"].quantile([0.025, 0.975]))     # report the curve only where the group has data
            inside = (ages >= lo) & (ages <= hi)
            fine = np.arange(np.ceil(lo * 4) / 4, hi, 0.25)
            fv = hinge_design(fine) @ c
            cross = fine[np.argmax(fv < 0)] if (fv < 0).any() and (fv >= 0).any() and fv[0] >= 0 else None
            rows[str(grp)] = {"n": int(len(g)), "mean_age": round(float(g["age"].mean()), 1), "age_range_95": [round(lo, 1), round(hi, 1)],
                              "curve": {int(a): (round(float(v), 4) if ok else None) for a, v, ok in zip(ages, vals, inside)},
                              "curve_points": {int(a): (round(float(v) * POINTS_PER_RESIDUAL, 0) if ok else None) for a, v, ok in zip(ages, vals, inside)},
                              "age_curve_crosses_zero": None if cross is None else float(cross)}
        entry = {"description": GROUPS[col], "by_group": rows}
        a, b = contrasts[col]
        if a in rows and b in rows:
            ga, gb = men[men[col] == a], men[men[col] == b]
            ia, ib = inv[(men[col] == a).to_numpy()], inv[(men[col] == b).to_numpy()]
            diffs = np.empty((reps, len(ages)))
            Xa, ya = hinge_design(ga["age"].to_numpy(dtype=float)), ga["r"].to_numpy(dtype=float)
            Xb, yb = hinge_design(gb["age"].to_numpy(dtype=float)), gb["r"].to_numpy(dtype=float)
            reg = np.diag([0.0, 1.0] + [10.0] * len(KNOTS))
            for i in range(reps):
                pick = rng.integers(0, len(ev_ids), len(ev_ids))
                w = np.bincount(pick, minlength=len(ev_ids)).astype(float)
                wa, wb = w[ia], w[ib]
                ca = np.linalg.solve(Xa.T @ (Xa * wa[:, None]) + reg, Xa.T @ (wa * ya))
                cb = np.linalg.solve(Xb.T @ (Xb * wb[:, None]) + reg, Xb.T @ (wb * yb))
                diffs[i] = X @ (ca - cb)
            both_have = [int(x) for x in ages if rows[a]["curve"][int(x)] is not None and rows[b]["curve"][int(x)] is not None]
            entry["contrast"] = {"difference": f"{a} minus {b}", "note": "ages where both groups have data (central 95% of each group's ages)",
                                 "by_age": {int(x): {"difference": round(rows[a]["curve"][int(x)] - rows[b]["curve"][int(x)], 4),
                                                     "ci95": [round(float(q), 4) for q in np.quantile(diffs[:, j], [0.025, 0.975])]}
                                            for j, x in enumerate(ages) if int(x) in both_have}}
        out["groups"][col] = entry
    return out


# ---------- the published index (weekly pipeline; frozen settings in config/decline.yaml) ----------

def load_config() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "config" / "decline.yaml").read_text())


def label_index(idx: pd.DataFrame, threshold_points: float = 30.0) -> pd.DataFrame:
    """Plain-language reading of each row: ahead of, in line with, or behind the rating, with the two components in
    rating points. Written for the fighter pages; the thresholds are presentation choices, not model parameters."""
    idx = idx.copy()
    k = POINTS_PER_RESIDUAL
    total = idx["total_prediction"].to_numpy(dtype=float) * k
    pop = idx["population_expectation"].to_numpy(dtype=float) * k
    ind = idx["individual_prediction"].to_numpy(dtype=float) * k
    idx["label"] = np.select([total >= threshold_points, total <= -threshold_points], ["ahead of rating", "behind rating"], "in line with rating")
    idx["age_component_points"] = np.round(pop, 0)
    idx["own_results_points"] = np.round(ind, 0)
    female = idx["female"].to_numpy() if "female" in idx.columns else np.zeros(len(idx), dtype=int)

    def text(t: float, p: float, i: float, her: bool) -> str:
        pro, obj = ("her", "her") if her else ("his", "him")
        if abs(t) < threshold_points:
            return f"Recent performances are in line with the rating ({t:+.0f} points)."
        side = "ahead of" if t > 0 else "behind"
        head = f"Recent performances run about {abs(t):.0f} points {side} the rating"
        if abs(p) < 10 and abs(i) < 10:
            return head + "."
        if abs(p) < 10:
            return f"{head}: {pro} own recent results, not age, put {obj} there."
        age_part = f"fighters this age typically run {abs(p):.0f} points {'ahead of' if p > 0 else 'behind'} their rating"
        if abs(i) < 10:
            return f"{head}: {age_part}, and {pro} own recent results track that."
        if (p < 0) == (i < 0):
            own = f"{pro} own recent results put {obj} a further {abs(i):.0f} points {'ahead' if i > 0 else 'behind'}"
        else:
            own = f"{pro} own recent results {'recover' if i > 0 else 'give back'} {abs(i):.0f} of those points"
        return f"{head}: {age_part}, and {own}."
    idx["reading"] = [text(t, p, i, bool(f)) for t, p, i, f in zip(total, pop, ind, female)]
    return idx


def publish_index(verbose: bool = True) -> pd.DataFrame:
    """Recompute outputs/decline_index.csv and outputs/decline_curve.json from the frozen settings."""
    cfg = load_config()
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    rated = pd.read_csv(PROC / "bouts_rated.csv", parse_dates=["date"])
    fighters = pd.read_csv(PROC / "fighters.csv")
    t = residual_table(bouts, rated, fighters, rating=cfg["rating"], outcome=cfg["outcome"])
    hp = {"lambda_level": float(cfg["lambda_level"]), "lambda_slope": float(cfg["lambda_slope"]), "half_life": float(cfg["half_life"])}
    as_of = bouts["date"].max() + pd.Timedelta(days=1)
    idx = label_index(index_as_of(t, as_of, hp))
    recent = pd.to_datetime(idx["last_bout"]) >= as_of - pd.Timedelta(days=int(cfg.get("max_idle_days", 1096)))
    idx = idx[recent].reset_index(drop=True)             # an index is a statement about recent form; retired careers are left out
    full, fitted = set_outcome(t, t, (t["date"] >= TUNE_FROM).to_numpy())
    coefs = fit_population(full[full["date"] >= TUNE_FROM])
    ages = np.arange(20, 45).astype(float)
    curve = {"as_of": as_of.date().isoformat(), "rating": cfg["rating"], "outcome": cfg["outcome"], "hyperparameters": hp,
             "corner_points": fitted["corner_points"], "points_per_residual": round(POINTS_PER_RESIDUAL, 1),
             "fighter_bouts_fitted": int(((full["date"] >= TUNE_FROM) & full["age"].notna()).sum()),
             "population_curve_men": {int(a): round(float(v), 4) for a, v in zip(ages, population_curve(ages, np.zeros(len(ages), dtype=int), coefs))},
             "population_curve_women": {int(a): round(float(v), 4) for a, v in zip(ages, population_curve(ages, np.ones(len(ages), dtype=int), coefs))},
             "fighters_indexed": int(len(idx)),
             "reading": "residual = performance score minus the rating's expectation; positive means the fighter has been doing better than "
                        "his rating implied. The population curve is the average residual at each age; the individual terms are the "
                        "fighter's own recency-weighted mean and trend, shrunk toward zero. One unit is about 695 rating points."}
    OUT.mkdir(exist_ok=True)
    idx.to_csv(OUT / "decline_index.csv", index=False)
    (OUT / "decline_curve.json").write_text(json.dumps(curve, indent=2))
    # every indexed fighter's own residual series, for the profile pages' trajectory chart (derived, not committed)
    res = full[full["fighter"].isin(idx["fighter"])].copy()
    res["population_curve"] = population_curve(res["age"].to_numpy(), res["female"].to_numpy(), coefs)
    res = res[["fighter", "date", "bout_id", "opponent", "won", "age", "e", "s", "r", "population_curve"]].sort_values(["fighter", "date"])
    res.to_csv(OUT / "decline_residuals.csv", index=False, float_format="%.4f")
    if verbose:
        print(f"decline index: {len(idx)} fighters as of {curve['as_of']}; corner {fitted['corner_points']} points; "
              f"men's curve 25: {curve['population_curve_men'][25]:+.3f}, 35: {curve['population_curve_men'][35]:+.3f}, 40: {curve['population_curve_men'][40]:+.3f}")
    return idx


# ---------- driver ----------

def run(rating: str = "elo", outcome: str = "perf", tune: bool = True, verbose: bool = True, group_col: str | None = None,
        stratified: bool = False) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    t0 = time.time()
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    rated = pd.read_csv(PROC / "bouts_rated.csv", parse_dates=["date"])
    fighters = pd.read_csv(PROC / "fighters.csv")
    t = residual_table(bouts, rated, fighters, rating=rating, outcome=outcome)
    if group_col or stratified:
        from mmalab.career_stats import bout_features
        t = attach_groups(t, bout_features(bouts, fighters))
    per_year, held, chosen = walk_forward(t, tune=tune, verbose=verbose, group_col=group_col)
    pooled = score_rows(held)
    report = {"rating_for_expectation": rating, "outcome": outcome, "tuned": tune, "grid": GRID if tune else None,
              "population_curve_group": group_col, "hyperparameters_by_year": chosen, "pooled_heldout": pooled, "per_year": per_year,
              "heldout_by_age": heldout_by_age(held), "result_test": result_test(held, rated, fighters), "decliner_test": decliner_test(held)}
    hp_last = {k: chosen[-1][k] for k in DEFAULT_HP} if chosen else dict(DEFAULT_HP)
    as_of = bouts["date"].max() + pd.Timedelta(days=1)
    idx = index_as_of(t, as_of, hp_last, group_col=group_col)
    full, fitted = set_outcome(t, t, (t["date"] >= TUNE_FROM).to_numpy())
    report["fitted_on_all_data"] = fitted
    if outcome == "perf":
        coefs = fit_population(full[full["date"] >= TUNE_FROM])
        ages = np.arange(21, 43).astype(float)
        report["population_curve_men"] = {int(a): round(float(v), 4) for a, v in zip(ages, population_curve(ages, np.zeros(len(ages), dtype=int), coefs))}
        report["population_curve_women"] = {int(a): round(float(v), 4) for a, v in zip(ages, population_curve(ages, np.ones(len(ages), dtype=int), coefs))}
    if stratified:
        report["stratified"] = stratified_report(full)
    report["index_as_of"] = as_of.date().isoformat()
    report["index_hyperparameters"] = hp_last
    report["points_per_residual_unit"] = round(POINTS_PER_RESIDUAL, 1)
    report["runtime_seconds"] = round(time.time() - t0, 1)
    return report, held, idx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rating", choices=["elo", "resume"], default="elo")
    ap.add_argument("--outcome", choices=["perf", "margin"], default="perf")
    ap.add_argument("--no-tune", action="store_true")
    ap.add_argument("--group", choices=sorted(GROUPS), default=None, help="population curve per fighter group (out-of-sample test)")
    ap.add_argument("--stratified", action="store_true", help="descriptive curves by every group, with bootstrap contrasts")
    ap.add_argument("--index-only", action="store_true", help="recompute the published index from config/decline.yaml (pipeline step)")
    ap.add_argument("--suffix", default="")
    args = ap.parse_args()
    if args.index_only:
        publish_index()
        return
    report, held, idx = run(args.rating, args.outcome, tune=not args.no_tune, group_col=args.group, stratified=args.stratified)
    OUT.mkdir(exist_ok=True)
    tag = args.suffix or (f"_research_{args.rating}_{args.outcome}" + (f"_by_{args.group}" if args.group else ""))
    (OUT / f"decline_report{tag}.json").write_text(json.dumps(report, indent=2, default=str))
    idx.to_csv(OUT / f"decline_index{tag}.csv", index=False)
    held.to_csv(OUT / f"decline_heldout{tag}.csv", index=False)
    print(json.dumps({k: v for k, v in report.items() if k not in ("population_curve_men", "population_curve_women", "per_year", "stratified")}, indent=1, default=str))


if __name__ == "__main__":
    main()
