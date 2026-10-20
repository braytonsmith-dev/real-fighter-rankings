"""
profiles.py - Fighter profiles: does age in context beat age alone, and which career statistics mark the outlier?

Research question (Oct 20, 2026): the board's favourite aged 35 or older wins 45% of bouts against about 60% for
younger favourites. Age alone cannot say which older fighter is done and which is still elite, so this module tests
whether career statistics (mileage, damage absorbed, knockout losses, style, activity, trajectory) carry information
beyond age, and turns the fitted model into two per-fighter indices shown beside the resume rank:

  decline index   how far the profile moves a fighter below what his rating says (rating-point equivalents)
  rise index      how far it moves him above

Method. Walk-forward logistic layers on top of the frozen v1.0 predictive probability (p_elo), exactly as the shadow
prediction model does (src/mmalab/shadow.py): for each test year Y from 2016, fit on bouts from 2011 to Y-1, score Y.
Four nested models are compared on identical bouts with paired event-block bootstraps:

  M0  logit(p_elo) only (a recalibration)
  M1  M0 + the shadow model's pre-fight features (age, over-33, layoff, debut, experience, height, five rounds)
  M2  M1 + profile differences (career statistics of a minus b, from career_stats.bout_features)
  M3  M2 + age interactions (over-33 years x damage absorbed, x knockout losses, x grappling share, x activity)

Every feature is a difference (a minus b), so the model is symmetric and a fighter's own contribution is linear in his
statistics: index_i = sum_k w_k * (x_ik - median_k) / sd_k over the profile columns, converted to rating points
through the fitted weight on the Elo difference. Outputs: outputs/profiles_report.json, outputs/profiles_by_year.csv,
outputs/profiles_model.json, outputs/fighter_profiles.csv (every board fighter's statistics and indices as of the data date).

    PYTHONPATH=src python3 -m mmalab.profiles
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from mmalab.shadow import Logistic, features as shadow_features, metrics, paired_bootstrap

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"

TUNE_FROM = pd.Timestamp("2011-01-01")
FIRST_TEST_YEAR = 2016
L2 = 2.0

BASE_COLS = ["elo_logit"]
SHADOW_COLS = ["age_diff", "old_diff", "layoff_diff", "debut_diff", "exp_diff", "height_diff", "five_round", "elo_x_five"]
# profile columns are taken from career_stats.bout_features as <name>_diff; the list is the hypothesis set
PROFILE_COLS = ["sapm", "slpm", "sig_def", "sig_acc", "kd_against_per15", "kd_for_per15", "ko_losses_3y", "ko_losses_rate", "sub_losses_rate",
                "cum_sig_absorbed_log", "cum_kd_against", "minutes_log", "bouts_per_year", "td_avg", "td_def", "ctrl_share", "grappling_share",
                "finish_rate_for", "finished_rate_against", "debut_age", "ufc_years", "win_rate_last5", "traj", "surprise"]
INTERACTIONS = [("old", "kd_against_per15"), ("old", "ko_losses_3y"), ("old", "cum_sig_absorbed_log"), ("old", "sapm"),
                ("old", "grappling_share"), ("old", "bouts_per_year"), ("old", "ufc_years"), ("old", "debut_age"), ("old", "minutes_log")]


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def derive(bf: pd.DataFrame) -> pd.DataFrame:
    """Derived per-fighter columns for both sides: debut age, log mileage, loss rates."""
    bf = bf.copy()
    for side in ("a", "b"):
        n = bf[f"n_bouts_{side}"].astype(float)
        bf[f"debut_age_{side}"] = bf[f"age_{side}"] - bf[f"ufc_years_{side}"]
        bf[f"cum_sig_absorbed_log_{side}"] = np.log1p(bf[f"cum_sig_absorbed_{side}"].astype(float))
        bf[f"minutes_log_{side}"] = np.log1p(bf[f"minutes_{side}"].astype(float))
        bf[f"ko_losses_rate_{side}"] = bf[f"ko_losses_{side}"].astype(float) / n.clip(lower=1)
        bf[f"sub_losses_rate_{side}"] = bf[f"sub_losses_{side}"].astype(float) / n.clip(lower=1)
    return bf


def trajectory(rated: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    """Per bout and side, the fighter's mean rating change and mean result surprise (result minus p) over his previous
    `window` bouts, computed chronologically from the predictive Elo file. Debutants get NaN."""
    r = rated.sort_values(["date", "bout_id"])
    rows = []
    for side, other in (("a", "b"), ("b", "a")):
        res = r["result_a"] if side == "a" else 1 - r["result_a"]
        p = r["p_a"] if side == "a" else 1 - r["p_a"]
        rows.append(pd.DataFrame({"bout_id": r["bout_id"], "fighter": r[f"fighter_{side}"], "date": r["date"], "side": side,
                                  "delta": r[f"elo_post_{side}"] - r[f"elo_pre_{side}"], "surprise": res - p}))
    long = pd.concat(rows).sort_values(["date", "bout_id"])
    g = long.groupby("fighter")
    long["traj"] = g["delta"].transform(lambda x: x.shift(1).rolling(window, min_periods=1).mean())
    long["surprise_prev"] = g["surprise"].transform(lambda x: x.shift(1).rolling(window, min_periods=1).mean())
    piv = long.pivot(index="bout_id", columns="side", values=["traj", "surprise_prev"])
    out = pd.DataFrame(index=piv.index)
    for side in ("a", "b"):
        out[f"traj_{side}"] = piv[("traj", side)]
        out[f"surprise_{side}"] = piv[("surprise_prev", side)]
    return out


def build_features(rated: pd.DataFrame, fighters: pd.DataFrame, bout_feats: pd.DataFrame) -> pd.DataFrame:
    """One row per bout: shadow features, profile differences and interactions, with y and dates."""
    f = shadow_features(rated, fighters, corner_adv=0.0)
    f["elo_logit"] = _logit(f["p_elo"].to_numpy(dtype=float))
    bf = derive(bout_feats.set_index("bout_id") if "bout_id" in bout_feats.columns else bout_feats)
    bf = bf.join(trajectory(rated), how="left")
    bf = bf.reindex(f.index)
    for col in PROFILE_COLS:
        a, b = bf.get(f"{col}_a"), bf.get(f"{col}_b")
        if a is None or b is None:
            continue
        a, b = a.astype(float), b.astype(float)
        med = pd.concat([a, b]).median()
        f[f"{col}_diff"] = (a.fillna(med) - b.fillna(med)).to_numpy()
    r = rated.set_index("bout_id").reindex(f.index)
    dob = pd.to_datetime(fighters.set_index("fighter")["dob"], errors="coerce")
    age_a = (r["date"] - dob.reindex(r["fighter_a"]).to_numpy()).dt.days / 365.25
    age_b = (r["date"] - dob.reindex(r["fighter_b"]).to_numpy()).dt.days / 365.25
    old_a = (age_a.clip(lower=33) - 33).fillna(0.0).to_numpy()
    old_b = (age_b.clip(lower=33) - 33).fillna(0.0).to_numpy()
    for _, col in INTERACTIONS:
        a, b = bf.get(f"{col}_a"), bf.get(f"{col}_b")
        if a is None or b is None:
            continue
        a, b = a.astype(float), b.astype(float)
        med = pd.concat([a, b]).median()
        f[f"old_x_{col}_diff"] = old_a * a.fillna(med).to_numpy() - old_b * b.fillna(med).to_numpy()
    f["event"] = r["event"].to_numpy()
    f["fighter_a"], f["fighter_b"] = r["fighter_a"].to_numpy(), r["fighter_b"].to_numpy()
    f["old_either"] = ((age_a >= 33) | (age_b >= 33)).fillna(False).to_numpy()
    return f


def model_columns(f: pd.DataFrame) -> dict[str, list[str]]:
    prof = [c for c in (f"{c}_diff" for c in PROFILE_COLS) if c in f.columns]
    inter = [c for c in (f"old_x_{c}_diff" for _, c in INTERACTIONS) if c in f.columns]
    return {"M0": BASE_COLS, "M1": BASE_COLS + SHADOW_COLS, "M2": BASE_COLS + SHADOW_COLS + prof,
            "M3": BASE_COLS + SHADOW_COLS + prof + inter}


def walk_forward(f: pd.DataFrame, cols: dict[str, list[str]], l2: float = L2) -> tuple[pd.DataFrame, list[dict]]:
    """Held-out probabilities for every model and test year; returns the per-bout frame and a per-year table."""
    f = f[f["y"].isin([0.0, 1.0]) & (f["date"] >= TUNE_FROM)].copy()
    years = f["date"].dt.year
    preds = {m: np.full(len(f), np.nan) for m in cols}
    rows = []
    for yr in range(FIRST_TEST_YEAR, int(years.max()) + 1):
        train, test = (years < yr).to_numpy(), (years == yr).to_numpy()
        if train.sum() < 500 or test.sum() == 0:
            continue
        row = {"year": yr, "train": int(train.sum()), "test": int(test.sum())}
        for m, c in cols.items():
            mdl = Logistic(c).fit(f[train], l2=l2)
            p = mdl.predict(f[test])
            preds[m][test] = p
            row[m] = metrics(f["y"].to_numpy(dtype=float)[test], p)
        rows.append(row)
    for m in cols:
        f[f"p_{m}"] = preds[m]
    return f[f[f"p_{list(cols)[0]}"].notna()].copy(), rows


def summarize(f: pd.DataFrame, cols: dict[str, list[str]]) -> dict:
    y = f["y"].to_numpy(dtype=float)
    ev = f["event"].astype(str).to_numpy() + "|" + f["date"].dt.strftime("%Y-%m-%d").to_numpy()
    out = {"bouts": int(len(f)), "window": [str(f["date"].min().date()), str(f["date"].max().date())], "models": {}}
    ll = {}
    for m in cols:
        p = np.clip(f[f"p_{m}"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
        ll[m] = -(y * np.log(p) + (1 - y) * np.log(1 - p))
        out["models"][m] = metrics(y, p) | {"features": len(cols[m])}
    for a, b in (("M1", "M0"), ("M2", "M1"), ("M3", "M1"), ("M3", "M2")):
        d = ll[b] - ll[a]
        out[f"gain_{a}_over_{b}"] = {"delta_log_loss": round(float(d.mean()), 4), "ci95_event_block_bootstrap": paired_bootstrap(d, ev)}
    old = f["old_either"].to_numpy(dtype=bool)
    out["bouts_with_a_fighter_33_or_over"] = {"bouts": int(old.sum())}
    for m in cols:
        out["bouts_with_a_fighter_33_or_over"][m] = metrics(y[old], np.clip(f[f"p_{m}"].to_numpy(dtype=float)[old], 1e-6, 1 - 1e-6))
    for a, b in (("M2", "M1"), ("M3", "M1")):
        d = (ll[b] - ll[a])[old]
        out["bouts_with_a_fighter_33_or_over"][f"gain_{a}_over_{b}"] = {"delta_log_loss": round(float(d.mean()), 4), "ci95": paired_bootstrap(d, ev[old])}
    return out


def fighter_indices(f: pd.DataFrame, cols: list[str], bout_feats_as_of: pd.DataFrame, l2: float = L2) -> tuple[pd.DataFrame, dict]:
    """Fit the full model on every bout, then express each fighter's own profile as rating points relative to the
    median fighter: positive = the profile adds to what the rating says, negative = it subtracts."""
    mdl = Logistic(cols).fit(f[f["y"].isin([0.0, 1.0]) & (f["date"] >= TUNE_FROM)], l2=l2)
    w = dict(zip(cols, mdl.w[1:]))
    sd = dict(zip(cols, mdl.sd))
    w_elo = w["elo_logit"] / sd["elo_logit"]            # logit per unit of logit(p_elo)
    # one logit of p_elo corresponds to 400 / ln(10) ... the Elo expected-score curve: p = 1 / (1 + 10^(-d/400))
    logit_per_point = w_elo * np.log(10) / 400.0         # logit per rating point of Elo difference
    prof_cols = [c for c in cols if c.endswith("_diff") and c not in SHADOW_COLS]
    X = bout_feats_as_of.copy()
    contrib = pd.DataFrame(index=X.index)
    for c in prof_cols:
        base = c[:-5]
        if base.startswith("old_x_"):
            src = base[len("old_x_"):]
            if src not in X.columns or "old" not in X.columns:
                continue
            x = X["old"].astype(float).fillna(0.0) * X[src].astype(float).fillna(0.0)
        else:
            if base not in X.columns:
                continue
            x = X[base].astype(float)
        x = x.fillna(x.median())
        contrib[c] = w[c] * (x - x.median()) / sd[c]
    logit_total = contrib.sum(axis=1)
    points = logit_total / logit_per_point if logit_per_point > 0 else logit_total * np.nan
    res = pd.DataFrame({"profile_points": points.round(1), "profile_logit": logit_total.round(4)}, index=X.index)
    top = contrib.abs().mean().sort_values(ascending=False)
    for c in top.index:
        res[f"c_{c}"] = (contrib[c] / logit_per_point).round(1) if logit_per_point > 0 else contrib[c]
    return res, {"features": cols, "weights": w, "sd": sd, "logit_per_rating_point": float(logit_per_point),
                 "mean_abs_contribution_points": {c: float(v / logit_per_point) for c, v in top.items()} if logit_per_point > 0 else {}}


def main() -> None:
    from mmalab import career_stats
    t0 = time.time()
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    rated = pd.read_csv(PROC / "bouts_rated.csv", parse_dates=["date"])
    fighters = pd.read_csv(PROC / "fighters.csv")
    bf = career_stats.bout_features(bouts)
    f = build_features(rated, fighters, bf)
    cols = model_columns(f)
    held, by_year = walk_forward(f, cols)
    report = summarize(held, cols)
    report["by_year"] = by_year
    report["runtime_seconds"] = round(time.time() - t0, 1)
    OUT.mkdir(exist_ok=True)
    (OUT / "profiles_report.json").write_text(json.dumps(report, indent=2, default=str))
    pd.DataFrame(by_year).to_csv(OUT / "profiles_by_year.csv", index=False)
    print(json.dumps({k: v for k, v in report.items() if k != "by_year"}, indent=1, default=str))


if __name__ == "__main__":
    main()
