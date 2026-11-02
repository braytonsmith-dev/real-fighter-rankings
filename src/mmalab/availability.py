"""
availability.py - Matchmaking track, step 1: will a fighter compete in the next H days?

Separate from the frozen v1.0 board. It reads data/processed/bouts.csv, fighters.csv and elo_history.csv, writes
nothing that the board reads, and changes no rating or rank.

Question. On a snapshot date t, for every fighter whose last UFC bout falls in the 540 days before t (the board's
activity window), what is the probability that he has a UFC bout dated in [t, t + H)? H = 120 days is the primary
horizon (UFC bookings are usually public 6 to 10 weeks out, so a matchmaking prediction has to look this far);
60 and 180 days are reported as secondary.

Design.
  * Snapshots on the first day of every month. Training snapshots 2015-01 to 2021-12; held-out test snapshots
    2022-01 to 2025-12 (the user's 2015-2025 window). Every H-day target window of a test snapshot closes before the
    end of the data.
  * Features use only bouts dated strictly before t, ratings from bouts before t, and age at t. No leakage.
  * Leaving the UFC (release, retirement) is a real "no", not censoring: a matchmaker cannot book that fighter.
  * Baselines scored on the same rows: B0 constant training rate; B1 empirical rate by days-since-last-bout bucket;
    B2 empirical rate by days-since bucket crossed with the fighter's own usual gap (the "bare minimum" average
    time between fights). Model M: L2 logistic regression on the features below.
  * Intervals: paired bootstrap over snapshot months (each month resampled whole), 2,000 draws.

Run:  PYTHONPATH=src python3 -m mmalab.availability
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs" / "matchmaking"

ACTIVE_DAYS = 540
HORIZONS = (60, 120, 180)
PRIMARY = 120
TRAIN = ("2015-01-01", "2021-12-01")
TEST = ("2022-01-01", "2025-12-01")
WOMEN = {"Women's Strawweight", "Women's Flyweight", "Women's Bantamweight", "Women's Featherweight"}
SHRINK_K = 2.0          # prior gaps worth of weight given to the population log-gap
DAYS_BUCKETS = [0, 45, 90, 150, 240, 365, ACTIVE_DAYS + 1]
RATIO_BUCKETS = [-np.inf, -0.7, -0.25, 0.25, 0.7, np.inf]

FEATURES = [
    "log_days", "log_days_sq", "log_gap", "log_ratio", "log_ratio_sq", "log_n", "debut_only",
    "last_win", "last_ko_loss", "last_other_loss", "last_nodecision", "last_finish_win", "streak",
    "losses_last3", "last_title", "title_winner", "age_c", "age_c_sq", "age_missing", "rating_pct", "women", "year_c",
]


def _long(bouts: pd.DataFrame) -> pd.DataFrame:
    b = bouts.sort_values(["date", "bout_id"], kind="stable")
    rows = []
    for side, opp in (("a", "b"), ("b", "a")):
        res = b["result_a"] if side == "a" else 1.0 - b["result_a"]
        rows.append(pd.DataFrame({"fighter": b[f"fighter_{side}"].to_numpy(), "date": b["date"].to_numpy(),
                                  "bout_id": b["bout_id"].to_numpy(), "division": b["division"].to_numpy(),
                                  "result": res.to_numpy(dtype=float), "method": b["method"].to_numpy(),
                                  "title": b["title_fight"].astype(bool).to_numpy()}))
    L = pd.concat(rows, ignore_index=True)
    return L.sort_values(["fighter", "date", "bout_id"], kind="stable").reset_index(drop=True)


def _rating_pct(elo: pd.DataFrame, t: pd.Timestamp, pool: pd.DataFrame) -> pd.Series:
    """Percentile of each pool fighter's latest pre-t rating within his last division's active pool."""
    e = elo[elo["date"] < t].groupby("fighter").tail(1).set_index("fighter")["rating"]
    r = pool[["fighter", "division"]].copy()
    r["rating"] = r["fighter"].map(e)
    pct = r.groupby("division")["rating"].rank(pct=True)
    return pct.fillna(0.5).set_axis(r["fighter"]).astype(float)


def build_panel(bouts: pd.DataFrame | None = None, fighters: pd.DataFrame | None = None,
                elo: pd.DataFrame | None = None, start: str = TRAIN[0], end: str = TEST[1]) -> pd.DataFrame:
    """One row per (snapshot, active fighter) with features and the three targets."""
    if bouts is None:
        bouts = pd.read_csv(PROC / "bouts.csv")
    if fighters is None:
        fighters = pd.read_csv(PROC / "fighters.csv")
    if elo is None:
        elo = pd.read_csv(PROC / "elo_history.csv")
    bouts = bouts.assign(date=pd.to_datetime(bouts["date"]))
    elo = elo.assign(date=pd.to_datetime(elo["date"])).sort_values(["date", "bout_id"], kind="stable")
    dob = pd.to_datetime(fighters.drop_duplicates("fighter").set_index("fighter")["dob"], errors="coerce")
    L = _long(bouts)
    by_f = {f: g.reset_index(drop=True) for f, g in L.groupby("fighter", sort=False)}
    all_dates = np.sort(L["date"].unique())
    frames = []
    for t in pd.date_range(start, end, freq="MS"):
        prior = L[L["date"] < t]
        last = prior.groupby("fighter").tail(1)
        pool = last[(t - last["date"]).dt.days <= ACTIVE_DAYS]
        # population log-gap from every gap observed before t (no leakage)
        gaps_all = prior.groupby("fighter")["date"].diff().dt.days.dropna()
        gaps_all = gaps_all[gaps_all > 0]
        pop_log_gap = float(np.log(gaps_all).mean())
        pct = _rating_pct(elo, t, pool)
        rows = []
        for f, div, ld in zip(pool["fighter"], pool["division"], pool["date"]):
            g = by_f[f]
            h = g[g["date"] < t]
            gaps = h["date"].diff().dt.days.dropna().to_numpy()
            gaps = gaps[gaps > 0]
            n = len(h)
            log_gap = (np.log(gaps).sum() + SHRINK_K * pop_log_gap) / (len(gaps) + SHRINK_K)
            days = (t - ld).days
            res = h["result"].to_numpy()
            lr, lm = res[-1], h["method"].iloc[-1]
            decided = res[~np.isnan(res) & (res != 0.5)]
            streak = 0
            for x in decided[::-1]:
                s = 1 if x == 1 else -1
                if streak == 0 or np.sign(streak) == s:
                    streak += s
                else:
                    break
            future = g.loc[g["date"] >= t, "date"]
            nxt = (future.iloc[0] - t).days if len(future) else np.inf
            age = (t - dob.get(f, pd.NaT)).days / 365.25 if pd.notna(dob.get(f, pd.NaT)) else np.nan
            rows.append({
                "snapshot": t, "fighter": f, "division": div, "days_since": days, "n_bouts": n,
                "own_gap_days": float(np.exp(log_gap)), "next_in_days": nxt, "age": age,
                "log_days": np.log(max(days, 1)), "log_gap": log_gap, "log_n": np.log1p(n),
                "debut_only": float(n == 1),
                "last_win": float(lr == 1), "last_ko_loss": float(lr == 0 and lm == "KO/TKO"),
                "last_other_loss": float(lr == 0 and lm != "KO/TKO"),
                "last_nodecision": float(np.isnan(lr) or lr == 0.5),
                "last_finish_win": float(lr == 1 and lm in ("KO/TKO", "SUB")),
                "streak": float(np.clip(streak, -5, 5)),
                "losses_last3": float((res[-3:] == 0).sum()),
                "last_title": float(h["title"].iloc[-1]),
                "title_winner": float(h["title"].iloc[-1] and lr == 1),
                "rating_pct": float(pct.get(f, 0.5)), "women": float(div in WOMEN),
            })
        P = pd.DataFrame(rows)
        frames.append(P)
    P = pd.concat(frames, ignore_index=True)
    P["log_ratio"] = P["log_days"] - P["log_gap"]
    P["log_ratio_sq"] = P["log_ratio"] ** 2
    P["log_days_sq"] = (P["log_days"] - 5.0) ** 2
    P["age_missing"] = P["age"].isna().astype(float)
    P["age_c"] = (P["age"] - 30.0).fillna(0.0)
    P["age_c_sq"] = P["age_c"] ** 2
    P["year_c"] = (P["snapshot"].dt.year - 2018) / 5.0
    for H in HORIZONS:
        P[f"y{H}"] = (P["next_in_days"] < H).astype(float)
    # the target window must close inside the data
    data_end = pd.Timestamp(all_dates[-1])
    for H in HORIZONS:
        P.loc[P["snapshot"] + pd.Timedelta(days=H) > data_end, f"y{H}"] = np.nan
    return P


# ---------- models ----------
def _logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    Xb = np.column_stack([np.ones(len(X)), X])
    pen = np.r_[0.0, np.full(X.shape[1], l2)]

    def f(w):
        z = Xb @ w
        ll = np.sum(np.logaddexp(0, z) - y * z)
        return ll + 0.5 * np.sum(pen * w * w), Xb.T @ (1 / (1 + np.exp(-z)) - y) + pen * w

    return minimize(f, np.zeros(Xb.shape[1]), jac=True, method="L-BFGS-B").x


def predict_logit(w, X):
    return 1 / (1 + np.exp(-(w[0] + X @ w[1:])))


def _bucket_rates(train: pd.DataFrame, test: pd.DataFrame, y: str, keys: list[str], prior_n: float = 20.0):
    base = train[y].mean()
    g = train.groupby(keys)[y].agg(["sum", "count"])
    rate = (g["sum"] + prior_n * base) / (g["count"] + prior_n)
    idx = pd.MultiIndex.from_frame(test[keys]) if len(keys) > 1 else test[keys[0]]
    return pd.Series(rate.reindex(idx).to_numpy(), index=test.index).fillna(base)


def _auc(y, p):
    from scipy.stats import rankdata
    r = rankdata(p)
    n1 = y.sum()
    n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def evaluate(P: pd.DataFrame, H: int, n_boot: int = 2000, seed: int = 7) -> dict:
    y = f"y{H}"
    D = P.dropna(subset=[y]).copy()
    D["days_b"] = pd.cut(D["days_since"], DAYS_BUCKETS, right=False, labels=False)
    D["ratio_b"] = pd.cut(D["log_ratio"], RATIO_BUCKETS, labels=False)
    tr = D[(D["snapshot"] >= TRAIN[0]) & (D["snapshot"] <= TRAIN[1])]
    te = D[(D["snapshot"] >= TEST[0]) & (D["snapshot"] <= TEST[1])].copy()
    mu, sd = tr[FEATURES].mean(), tr[FEATURES].std().replace(0, 1)
    w = fit_logit(((tr[FEATURES] - mu) / sd).to_numpy(), tr[y].to_numpy())
    te["M"] = predict_logit(w, ((te[FEATURES] - mu) / sd).to_numpy())
    te["B0"] = tr[y].mean()
    te["B1"] = _bucket_rates(tr, te, y, ["days_b"])
    te["B2"] = _bucket_rates(tr, te, y, ["days_b", "ratio_b"])
    yt = te[y].to_numpy()
    out = {"horizon_days": H, "train_rows": int(len(tr)), "test_rows": int(len(te)),
           "test_fighters": int(te["fighter"].nunique()), "test_snapshots": int(te["snapshot"].nunique()),
           "test_base_rate": round(float(yt.mean()), 4), "models": {}}
    for m in ("B0", "B1", "B2", "M"):
        p = te[m].to_numpy()
        out["models"][m] = {"log_loss": round(float(_logloss(yt, p).mean()), 4),
                            "brier": round(float(((p - yt) ** 2).mean()), 4),
                            "auc": None if m == "B0" else round(_auc(yt, p), 4)}
    # paired month-block bootstrap of log-loss differences, model minus baseline (negative = model better)
    rng = np.random.default_rng(seed)
    te["ll_M"] = _logloss(yt, te["M"].to_numpy())
    for b in ("B1", "B2"):
        te[f"d_{b}"] = te["ll_M"] - _logloss(yt, te[b].to_numpy())
    months = te.groupby("snapshot")[["d_B1", "d_B2"]].agg(["sum", "count"])
    keys = months.index.to_numpy()
    for b in ("B1", "B2"):
        s = months[(f"d_{b}", "sum")].to_numpy()
        c = months[(f"d_{b}", "count")].to_numpy()
        draws = []
        for _ in range(n_boot):
            i = rng.integers(0, len(keys), len(keys))
            draws.append(s[i].sum() / c[i].sum())
        out[f"M_minus_{b}_logloss"] = {"mean": round(float(s.sum() / c.sum()), 4),
                                       "ci95": [round(float(np.percentile(draws, 2.5)), 4),
                                                round(float(np.percentile(draws, 97.5)), 4)]}
    te["dec"] = pd.qcut(te["M"], 10, labels=False, duplicates="drop")
    out["calibration_M"] = [{"decile": int(k), "n": int(len(g)), "mean_pred": round(float(g["M"].mean()), 3),
                             "observed": round(float(g[y].mean()), 3)} for k, g in te.groupby("dec")]
    out["calibration_by_year_M"] = [{"year": int(k), "n": int(len(g)), "mean_pred": round(float(g["M"].mean()), 3),
                                     "observed": round(float(g[y].mean()), 3)}
                                    for k, g in te.groupby(te["snapshot"].dt.year)]
    out["coefficients_std"] = {k: round(float(v), 4) for k, v in zip(["intercept"] + FEATURES, w)}
    out["_test"] = te
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    P = build_panel()
    P.to_csv(OUT / "availability_panel.csv.gz", index=False)
    res = {}
    for H in HORIZONS:
        r = evaluate(P, H)
        te = r.pop("_test")
        res[H] = r
        if H == PRIMARY:
            te[["snapshot", "fighter", "division", "days_since", "own_gap_days", "next_in_days", f"y{H}",
                "B1", "B2", "M"]].to_csv(OUT / "availability_test_predictions.csv.gz", index=False)
    (OUT / "availability_backtest.json").write_text(json.dumps(res, indent=1, default=str))
    for H, r in res.items():
        print(f"H={H}: test rows {r['test_rows']}, base rate {r['test_base_rate']}")
        for m, v in r["models"].items():
            print(f"   {m}: log loss {v['log_loss']}, Brier {v['brier']}, AUC {v['auc']}")
        print(f"   M-B1 {r['M_minus_B1_logloss']}  M-B2 {r['M_minus_B2_logloss']}")


if __name__ == "__main__":
    main()
