"""
shadow.py - REAL v1.1 shadow prediction model: walk-forward tuning and validation over 2011-2026.

v1.0 is frozen (PREREGISTRATION.md). This module develops the next version without touching it:

  1. Walk-forward: for every test year Y from 2016 to the present, the Elo parameters are chosen on bouts
     from 2011 through Y-1 only (coordinate descent over an expanded space that adds a red-corner term and
     FiveThirtyEight-style damping of dominance credit for favorites), then scored on Y. No bout is ever
     used to pick the parameters that predict it. Aggregating the test years gives an honest 15-year
     out-of-sample record for the tuning procedure itself, not just for one parameter set.
  2. On top of the walk-forward Elo, a small L2-regularised logistic layer (fitted the same way, on
     2011..Y-1) adds age, layoff, experience, height and five-round-fight information.
  3. The frozen v1.0 model is scored on exactly the same bouts for the paired comparison.
  4. The final shadow parameters (tuned on 2011 to today) are saved to outputs/shadow_v11.json and used
     by picks.py as the 'shadow v1.1' column of the public ledger. They are never substituted for v1.0.

Outputs: outputs/shadow_v11_report.json, outputs/shadow_v11_by_year.csv, outputs/shadow_v11.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from mmalab.elo import EloParams, run_elo

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"

TUNE_FROM = pd.Timestamp("2011-01-01")
FIRST_TEST_YEAR = 2016

SPACE = {
    "k": [60, 80, 100, 130, 160, 200],
    "k_new_mult": [1.0, 1.5, 2.0, 2.5],
    "n_new": [3, 5, 8],
    "split_mult": [0.6, 0.8, 1.0],
    "finish_mult": [1.0, 1.25],
    "layoff_regress_per_year": [0.0, 0.15, 0.25, 0.4],
    "mov_weight": [0.5, 0.75, 0.9, 1.0],
    "mov_scale": [1.5, 2.0, 3.0, 4.0],
    "win_floor": [0.0, 0.5, 0.6],
    "finish_floor": [0.0, 0.6, 0.75],
    "corner_adv": [0.0, 20.0, 35.0, 50.0, 70.0],
    "mov_damp": [0.0, 0.0005, 0.001, 0.002],
}
FEATURES = ["elo_diff", "age_diff", "old_diff", "layoff_diff", "debut_diff", "exp_diff", "height_diff", "five_round", "elo_x_five"]


def _ll(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    return {"n": int(len(y)), "log_loss": round(_ll(y, p), 4), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "accuracy": round(float(np.mean((p > 0.5) == (y == 1))), 4)}


class Evaluator:
    """Caches run_elo by parameter tuple; scores any window."""

    def __init__(self, bouts: pd.DataFrame):
        self.bouts = bouts
        self.cache: dict[tuple, pd.DataFrame] = {}
        self.decided = bouts["result_a"].isin([0.0, 1.0]).to_numpy()

    def rated(self, params: dict) -> pd.DataFrame:
        key = tuple(sorted(params.items()))
        if key not in self.cache:
            self.cache[key], _ = run_elo(self.bouts, EloParams(**params))
        return self.cache[key]

    def loss(self, params: dict, start: pd.Timestamp, end: pd.Timestamp) -> float:
        r = self.rated(params)
        m = self.decided & (r["date"] >= start).to_numpy() & (r["date"] < end).to_numpy()
        return _ll(r.loc[m, "result_a"].to_numpy(), r.loc[m, "p_a"].to_numpy())


def coordinate_descent(ev: Evaluator, base: dict, start: pd.Timestamp, end: pd.Timestamp, sweeps: int = 3) -> tuple[dict, float, int]:
    best = dict(base)
    best_ll = ev.loss(best, start, end)
    evals = 1
    for _ in range(sweeps):
        improved = False
        for name, values in SPACE.items():
            for v in values:
                if v == best.get(name):
                    continue
                trial = {**best, name: v}
                ll = ev.loss(trial, start, end)
                evals += 1
                if ll < best_ll - 1e-6:
                    best, best_ll, improved = trial, ll, True
        if not improved:
            break
    return best, best_ll, evals


# ---------- logistic layer ----------

def features(rated: pd.DataFrame, fighters: pd.DataFrame, corner_adv: float) -> pd.DataFrame:
    """Pre-fight features for every bout, computed chronologically so nothing from the bout itself leaks."""
    r = rated.sort_values(["date", "bout_id"]).copy()
    dob = pd.to_datetime(fighters.set_index("fighter")["dob"], errors="coerce")
    height = fighters.set_index("fighter")["height_in"]
    long = pd.concat([
        r[["bout_id", "date", "fighter_a"]].rename(columns={"fighter_a": "fighter"}).assign(side="a"),
        r[["bout_id", "date", "fighter_b"]].rename(columns={"fighter_b": "fighter"}).assign(side="b")]).sort_values(["date", "bout_id"])
    long["prev_date"] = long.groupby("fighter")["date"].shift(1)
    long["prior_bouts"] = long.groupby("fighter").cumcount()
    long["layoff"] = (long["date"] - long["prev_date"]).dt.days
    piv = long.pivot(index="bout_id", columns="side", values=["prev_date", "prior_bouts", "layoff"])
    r = r.set_index("bout_id")
    f = pd.DataFrame(index=r.index)
    f["elo_diff"] = (r["elo_pre_a"] + corner_adv - r["elo_pre_b"]) / 400.0
    age_a = (r["date"] - dob.reindex(r["fighter_a"]).to_numpy()).dt.days / 365.25
    age_b = (r["date"] - dob.reindex(r["fighter_b"]).to_numpy()).dt.days / 365.25
    f["age_diff"] = (age_a - age_b).fillna(0.0)
    f["old_diff"] = (age_a.clip(lower=33) - 33).fillna(0.0) - (age_b.clip(lower=33) - 33).fillna(0.0)
    lay_a = piv[("layoff", "a")].reindex(r.index).astype(float).fillna(365.0).to_numpy()
    lay_b = piv[("layoff", "b")].reindex(r.index).astype(float).fillna(365.0).to_numpy()
    f["layoff_diff"] = np.log1p(lay_a) - np.log1p(lay_b)
    exp_a = piv[("prior_bouts", "a")].reindex(r.index).astype(float).fillna(0.0).to_numpy()
    exp_b = piv[("prior_bouts", "b")].reindex(r.index).astype(float).fillna(0.0).to_numpy()
    f["debut_diff"] = (exp_a == 0).astype(float) - (exp_b == 0).astype(float)
    f["exp_diff"] = np.log1p(exp_a) - np.log1p(exp_b)
    h_a, h_b = height.reindex(r["fighter_a"]).to_numpy(), height.reindex(r["fighter_b"]).to_numpy()
    f["height_diff"] = pd.Series(h_a - h_b, index=r.index).fillna(0.0)
    f["five_round"] = (r["sched_rounds"].fillna(3) >= 5).astype(float)
    f["elo_x_five"] = f["elo_diff"] * f["five_round"]
    f["date"] = r["date"]
    f["y"] = r["result_a"]
    f["p_elo"] = r["p_a"]
    return f


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    """Newton's method for L2-regularised logistic regression; the intercept (column 0) is not penalised."""
    n, d = X.shape
    w = np.zeros(d)
    reg = np.full(d, l2)
    reg[0] = 0.0
    for _ in range(iters):
        z = X @ w
        p = 1 / (1 + np.exp(-z))
        g = X.T @ (p - y) + reg * w
        W = p * (1 - p)
        H = (X * W[:, None]).T @ X + np.diag(reg)
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


class Logistic:
    def __init__(self, cols: list[str]):
        self.cols = cols
        self.mu = self.sd = self.w = None

    def fit(self, f: pd.DataFrame, l2: float = 1.0) -> "Logistic":
        X = f[self.cols].to_numpy(dtype=float)
        self.mu, self.sd = X.mean(axis=0), X.std(axis=0) + 1e-9
        Xs = np.column_stack([np.ones(len(X)), (X - self.mu) / self.sd])
        self.w = fit_logistic(Xs, f["y"].to_numpy(dtype=float), l2)
        return self

    def predict(self, f: pd.DataFrame) -> np.ndarray:
        X = f[self.cols].to_numpy(dtype=float)
        Xs = np.column_stack([np.ones(len(X)), (X - self.mu) / self.sd])
        return 1 / (1 + np.exp(-(Xs @ self.w)))

    def to_dict(self) -> dict:
        return {"features": self.cols, "mean": self.mu.tolist(), "std": self.sd.tolist(), "weights": self.w.tolist(),
                "note": "logit(p_a) = w0 + sum(w_i * (x_i - mean_i) / std_i)"}


# ---------- walk-forward ----------

def paired_bootstrap(d: np.ndarray, events: np.ndarray, reps: int = 5000, seed: int = 1) -> list[float]:
    rng = np.random.default_rng(seed)
    uniq = np.unique(events)
    idx = [np.where(events == e)[0] for e in uniq]
    draws = [d[np.concatenate([idx[k] for k in rng.integers(0, len(uniq), len(uniq))])].mean() for _ in range(reps)]
    return [round(float(x), 4) for x in np.percentile(draws, [2.5, 97.5])]


def main() -> None:
    t0 = time.time()
    rep = json.load(open(OUT / "backtest_report.json"))
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    fighters = pd.read_csv(PROC / "fighters.csv")
    ev = Evaluator(bouts)
    v10 = ev.rated(rep["tuned_params"]).set_index("bout_id")
    last_year = int(bouts["date"].max().year)
    years = list(range(FIRST_TEST_YEAR, last_year + 1))
    rows, per_year, chosen = [], [], {}
    base = dict(rep["tuned_params"])
    for Y in years:
        start, end = pd.Timestamp(f"{Y}-01-01"), pd.Timestamp(f"{Y + 1}-01-01")
        params, tune_ll, evals = coordinate_descent(ev, base, TUNE_FROM, start)
        base = params                                   # warm start the next year from this year's optimum
        chosen[Y] = params
        r = ev.rated(params)
        f = features(r, fighters, params["corner_adv"])
        f = f[f["y"].isin([0.0, 1.0])]
        tr, te = f[(f["date"] >= TUNE_FROM) & (f["date"] < start)], f[(f["date"] >= start) & (f["date"] < end)]
        lr = Logistic(FEATURES).fit(tr)
        recal = Logistic(["elo_diff"]).fit(tr)
        p_lr, p_recal = lr.predict(te), recal.predict(te)
        p10 = v10.loc[te.index, "p_a"].to_numpy()
        y = te["y"].to_numpy()
        per_year.append({"year": Y, "n": int(len(te)), "tune_bouts": int(len(tr)), "evals": evals, "tune_log_loss": round(tune_ll, 4),
                         "v10_log_loss": round(_ll(y, p10), 4), "v10_accuracy": round(float(np.mean((p10 > 0.5) == (y == 1))), 4),
                         "v11_elo_log_loss": round(_ll(y, te["p_elo"].to_numpy()), 4),
                         "v11_recal_log_loss": round(_ll(y, p_recal), 4),
                         "v11_lr_log_loss": round(_ll(y, p_lr), 4), "v11_lr_accuracy": round(float(np.mean((p_lr > 0.5) == (y == 1))), 4),
                         **{f"param_{k}": v for k, v in params.items() if k in SPACE}})
        rows.append(pd.DataFrame({"bout_id": te.index, "date": te["date"].to_numpy(), "event": r.set_index("bout_id").loc[te.index, "event"].to_numpy(),
                                  "y": y, "p_v10": p10, "p_v11_elo": te["p_elo"].to_numpy(), "p_v11_recal": p_recal, "p_v11_lr": p_lr}))
        print(f"{Y}: n={len(te)} evals={evals} tune={tune_ll:.4f} v1.0={per_year[-1]['v10_log_loss']:.4f} "
              f"v1.1 elo={per_year[-1]['v11_elo_log_loss']:.4f} +LR={per_year[-1]['v11_lr_log_loss']:.4f} ({time.time() - t0:.0f}s)")
    allp = pd.concat(rows, ignore_index=True)
    by_year = pd.DataFrame(per_year)
    by_year.to_csv(OUT / "shadow_v11_by_year.csv", index=False)

    def block(mask: np.ndarray, label: str) -> dict:
        d = allp[mask]
        y = d["y"].to_numpy()
        out = {"window": label, "bouts": int(len(d)), "events": int(d["event"].nunique())}
        for col, name in (("p_v10", "v1.0_frozen"), ("p_v11_elo", "v1.1_elo_walk_forward"), ("p_v11_recal", "v1.1_elo_recalibrated"), ("p_v11_lr", "v1.1_elo_plus_logistic")):
            out[name] = metrics(y, d[col].to_numpy())
        p10, p11 = np.clip(d["p_v10"].to_numpy(), 1e-6, 1 - 1e-6), np.clip(d["p_v11_lr"].to_numpy(), 1e-6, 1 - 1e-6)
        diff = (-(y * np.log(p10) + (1 - y) * np.log(1 - p10))) - (-(y * np.log(p11) + (1 - y) * np.log(1 - p11)))
        out["gain_v11_lr_over_v10"] = {"delta_log_loss": round(float(diff.mean()), 4),
                                       "ci95_event_block_bootstrap": paired_bootstrap(diff, d["event"].to_numpy())}
        c10, c11 = (p10 > 0.5) == (y == 1), (p11 > 0.5) == (y == 1)
        out["picks_fixed_vs_broken"] = [int(np.sum(c11 & ~c10)), int(np.sum(c10 & ~c11))]
        out["calibration_in_the_large"] = {"mean_p_v10": round(float(d["p_v10"].mean()), 4), "mean_p_v11_lr": round(float(d["p_v11_lr"].mean()), 4),
                                           "observed": round(float(y.mean()), 4)}
        return out

    yrs = pd.to_datetime(allp["date"]).dt.year
    report = {
        "method": "walk-forward: parameters and logistic weights chosen on 2011..Y-1, scored on Y, for Y in "
                  f"{years[0]}..{years[-1]}; v1.0 scored on the same bouts (note: v1.0 was tuned on 2010-2019, so it is in-sample before 2020)",
        "space": SPACE, "features": FEATURES,
        "all_test_years": block(np.ones(len(allp), bool), f"{years[0]}-{years[-1]}"),
        "out_of_sample_for_both": block((yrs >= 2020).to_numpy(), f"2020-{years[-1]}"),
        "parameters_by_year": {str(k): {kk: vv for kk, vv in v.items() if kk in SPACE} for k, v in chosen.items()},
    }
    # market comparison on the matched bouts inside the test years
    mk = OUT / "market_matched_bouts.csv"
    if mk.exists():
        m = pd.read_csv(mk)[["bout_id", "p_a_market"]].drop_duplicates("bout_id")
        j = allp.merge(m, on="bout_id")
        if len(j):
            y = j["y"].to_numpy()
            report["market_same_bouts"] = {"bouts": int(len(j)), "date_range": [str(pd.Timestamp(j['date'].min()).date()), str(pd.Timestamp(j['date'].max()).date())],
                                           "market": metrics(y, j["p_a_market"].to_numpy()), "v1.0": metrics(y, j["p_v10"].to_numpy()),
                                           "v1.1_elo_plus_logistic": metrics(y, j["p_v11_lr"].to_numpy()),
                                           "blend_v11_market_50_50": metrics(y, 0.5 * j["p_v11_lr"].to_numpy() + 0.5 * j["p_a_market"].to_numpy())}
    # final shadow parameters: everything from 2011 to today
    final, final_ll, evals = coordinate_descent(ev, base, TUNE_FROM, bouts["date"].max() + pd.Timedelta(days=1))
    r = ev.rated(final)
    f = features(r, fighters, final["corner_adv"])
    f = f[f["y"].isin([0.0, 1.0]) & (f["date"] >= TUNE_FROM)]
    lr = Logistic(FEATURES).fit(f)
    shadow = {"version": "shadow v1.1", "fitted_through": str(bouts["date"].max().date()), "tune_from": str(TUNE_FROM.date()),
              "elo_params": {k: v for k, v in final.items()}, "tune_log_loss": round(final_ll, 4), "logistic": lr.to_dict(),
              "status": "shadow only; never substituted for v1.0 (PREREGISTRATION.md section 9, appendix B)"}
    (OUT / "shadow_v11.json").write_text(json.dumps(shadow, indent=2))
    report["final_shadow_params"] = shadow["elo_params"]
    report["runtime_seconds"] = round(time.time() - t0)
    (OUT / "shadow_v11_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: report[k] for k in ("all_test_years", "out_of_sample_for_both")}, indent=1))
    print(json.dumps(report.get("market_same_bouts"), indent=1))
    print("final shadow params:", shadow["elo_params"])


if __name__ == "__main__":
    main()
