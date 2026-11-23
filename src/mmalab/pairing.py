"""
pairing.py - Matchmaking track, step 2: a ranked top-15 list of each fighter's likely next opponents.

Separate from the frozen v1.0 board; reads the availability panel (availability.py) and writes only to
outputs/matchmaking/.

Query. For every UFC bout between X and O on date d, ask "who is next for X?" at the first monthly snapshot t after
max(X's previous bout, d - 120 days). Everything is measured at t: X's and each candidate's record, ratings, official
rank, and the step-1 probability that the candidate fights in the next 120 days. The candidate pool is every fighter
active at t (last bout within 540 days) whose home division (last bout outside catch weight and open weight)
matches X's. The query is a hit at k if O is among the top k of the ranked pool.

Coverage. Some bouts cannot be hit by any same-division list: O debuts in that bout, O moves in from another
division, or X moves. They stay in the "all bouts" denominator as misses and are reported separately, so the
headline is honest about what a list built on UFC history alone can reach.

Model. Conditional logit over the pool (softmax of a linear score), fitted on queries from 2015-2021 bouts and
tested on 2022-2025 bouts. Baselines scored on the same queries: R1 nearest rating position in the division; R2 R1
plus the candidate's availability. Metrics: top-1/3/5/15 hit rate and mean reciprocal rank (MRR, 1/position of the
real opponent, 0 when absent). Intervals: paired bootstrap over event months, 2,000 draws.

Run:  PYTHONPATH=src python3 -m mmalab.pairing                      (backtest)
      PYTHONPATH=src python3 -m mmalab.pairing --lists 2026-11-01   (current top-15 lists)
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import logsumexp

from mmalab import availability as AV

OUT = AV.OUT
NON_DIVISIONS = {"Catch Weight", "Open Weight", "Unknown"}
LOOKBACK_DAYS = 120
TRAIN_BOUTS = ("2015-02-01", "2021-12-31")
TEST_BOUTS = ("2022-01-01", "2025-12-31")
TOPK = (1, 3, 5, 15)

PAIR_FEATURES = [
    "log_rank_gap", "rank_gap_up", "c_rank_pct", "x_rank_pct_x_c_rank_pct",
    "both_off_ranked", "log_off_gap", "c_ranked_x_unranked", "x_ranked_c_unranked", "c_champion", "x_champion",
    "c_avail_logit", "rematch", "c_beat_x_before",
    "streak_gap", "both_won_last", "c_lost_last", "log_n_gap", "c_debut_only", "age_gap", "log_days_gap",
]


# ---------- data ----------
def _bouts() -> pd.DataFrame:
    b = pd.read_csv(AV.PROC / "bouts.csv", parse_dates=["date"])
    return b.sort_values(["date", "bout_id"], kind="stable").reset_index(drop=True)


def _home_division(bouts: pd.DataFrame) -> pd.DataFrame:
    """Long table (fighter, date, home) where home is the fighter's division as of each bout, ignoring catch/open."""
    rows = []
    for side in ("a", "b"):
        rows.append(pd.DataFrame({"fighter": bouts[f"fighter_{side}"], "date": bouts["date"],
                                  "bout_id": bouts["bout_id"], "division": bouts["division"]}))
    L = pd.concat(rows).sort_values(["fighter", "date", "bout_id"], kind="stable")
    L["home"] = L["division"].where(~L["division"].isin(NON_DIVISIONS))
    L["home"] = L.groupby("fighter")["home"].ffill()
    return L


def availability_scores(P: pd.DataFrame, H: int = AV.PRIMARY) -> pd.Series:
    """Probability of a bout in the next H days for every panel row: the 2015-2021 fit for training years
    (in-sample, training only) and the deployable yearly refit for 2022 onward (EXP-2026-11-02-02: Platt added
    nothing once the model is refitted each year)."""
    y = f"y{H}"
    tr = P[(P["snapshot"] >= AV.TRAIN[0]) & (P["snapshot"] <= AV.TRAIN[1])].dropna(subset=[y])
    mu, sd = tr[AV.FEATURES].mean(), tr[AV.FEATURES].std().replace(0, 1)
    w = AV.fit_logit(((tr[AV.FEATURES] - mu) / sd).to_numpy(), tr[y].to_numpy())
    s = pd.Series(AV.predict_logit(w, ((P[AV.FEATURES] - mu) / sd).to_numpy()), index=P.index)
    years = sorted(y_ for y_ in P["snapshot"].dt.year.unique() if y_ >= 2022)
    if years:
        R = AV.rolling_predictions(P, H, years)
        key = pd.MultiIndex.from_frame(P[["snapshot", "fighter"]])
        roll = pd.Series(R["M_roll"].to_numpy(), index=pd.MultiIndex.from_frame(R[["snapshot", "fighter"]]))
        later = P["snapshot"].dt.year >= 2022
        s[later] = roll.reindex(key[later.to_numpy()]).to_numpy()
    return s


def prepare_panel(P: pd.DataFrame, bouts: pd.DataFrame) -> pd.DataFrame:
    """Add home division, rating position, official rank and availability to every panel row."""
    from mmalab.official_ranks import OfficialRanks
    P = P.copy()
    H = _home_division(bouts)
    P = P.sort_values("snapshot")
    homes = []
    for t, g in P.groupby("snapshot"):
        h = H[H["date"] < t].groupby("fighter")["home"].last()
        homes.append(pd.Series(g["fighter"].map(h).to_numpy(), index=g.index))
    P["home"] = pd.concat(homes)
    P["home"] = P["home"].fillna(P["division"])
    P["rank_pos"] = P.groupby(["snapshot", "home"])["rating_pct"].rank(ascending=False, method="first")
    P["pool_size"] = P.groupby(["snapshot", "home"])["fighter"].transform("size")
    P["rank_pct"] = 1 - (P["rank_pos"] - 1) / P["pool_size"].clip(lower=1)
    names = pd.concat([bouts["fighter_a"], bouts["fighter_b"]]).dropna().unique().tolist()
    O = OfficialRanks(names)
    P["off_rank"] = [O.rank(f, d, t) for f, d, t in zip(P["fighter"], P["home"], P["snapshot"])]
    P["avail"] = availability_scores(P)
    return P


# ---------- queries ----------
def build_queries(P: pd.DataFrame, bouts: pd.DataFrame, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (pairs, queries). pairs: one row per (query, candidate) with features and `target`; queries: one row per
    query with its coverage status."""
    snaps = np.array(sorted(P["snapshot"].unique()))
    by_snap = {t: g.set_index("fighter") for t, g in P.groupby("snapshot")}
    B = bouts[(bouts["date"] >= start) & (bouts["date"] <= end)]
    hist = pd.concat([pd.DataFrame({"fighter": bouts["fighter_a"], "opp": bouts["fighter_b"], "date": bouts["date"],
                                    "won": bouts["result_a"] == 1}),
                      pd.DataFrame({"fighter": bouts["fighter_b"], "opp": bouts["fighter_a"], "date": bouts["date"],
                                    "won": bouts["result_a"] == 0})])
    last_date = hist.groupby("fighter")["date"].apply(lambda s: np.sort(s.to_numpy()))
    meet = hist.groupby(["fighter", "opp"])
    meet_dates = meet["date"].apply(list).to_dict()
    meet_won = meet["won"].apply(list).to_dict()
    qrows, prow = [], []
    qid = 0
    for _, b in B.iterrows():
        for X, Ob in ((b["fighter_a"], b["fighter_b"]), (b["fighter_b"], b["fighter_a"])):
            d = b["date"]
            ds = last_date.get(X)
            prev = ds[ds < np.datetime64(d)] if ds is not None else []
            q = {"qid": qid, "date": d, "event": b["event"], "fighter": X, "opponent": Ob, "bout_division": b["division"]}
            qid += 1
            if len(prev) == 0:
                q["status"] = "x_debut"
                qrows.append(q)
                continue
            anchor = max(pd.Timestamp(prev[-1]), d - pd.Timedelta(days=LOOKBACK_DAYS))
            i = np.searchsorted(snaps, np.datetime64(anchor), side="right")
            if i >= len(snaps) or pd.Timestamp(snaps[i]) > d:
                q["status"] = "no_snapshot_before_bout"
                qrows.append(q)
                continue
            t = pd.Timestamp(snaps[i])
            S = by_snap[t]
            if X not in S.index:
                q["status"] = "x_inactive"
                qrows.append(q)
                continue
            x = S.loc[X]
            pool = S[(S["home"] == x["home"]) & (S.index != X)]
            q.update({"snapshot": t, "pool_size": len(pool), "home": x["home"]})
            if Ob not in S.index:
                q["status"] = "opp_debut_or_inactive"
            elif Ob not in pool.index:
                q["status"] = "opp_other_division"
            else:
                q["status"] = "eligible"
            qrows.append(q)
            if len(pool) == 0:
                continue
            f = _pair_features(X, x, pool, t, meet_dates, meet_won)
            f["qid"] = q["qid"]
            f["target"] = (pool.index == Ob).astype(float)
            prow.append(f.reset_index(drop=True))
    return pd.concat(prow, ignore_index=True), pd.DataFrame(qrows)


def _pair_features(X: str, x: pd.Series, C: pd.DataFrame, t: pd.Timestamp, meet_dates: dict, meet_won: dict) -> pd.DataFrame:
    """Features for every candidate C against fighter X, all measured at snapshot t."""
    f = pd.DataFrame(index=C.index)
    gap = C["rank_pos"] - x["rank_pos"]
    f["log_rank_gap"] = np.log1p(gap.abs())
    f["rank_gap_up"] = (gap < 0).astype(float) * np.log1p(gap.abs())
    f["c_rank_pct"] = C["rank_pct"]
    f["x_rank_pct_x_c_rank_pct"] = C["rank_pct"] * x["rank_pct"]
    xo, co = x["off_rank"], C["off_rank"]
    x_r = pd.notna(xo) and xo <= 15
    c_r = co.notna() & (co <= 15)
    f["both_off_ranked"] = (c_r & x_r).astype(float)
    f["log_off_gap"] = np.where(c_r & x_r, np.log1p((co - (xo if x_r else 0)).abs()), 0.0)
    f["c_ranked_x_unranked"] = (c_r & (not x_r)).astype(float)
    f["x_ranked_c_unranked"] = ((~c_r) & x_r).astype(float)
    f["c_champion"] = (co == 0).astype(float)
    f["x_champion"] = float(xo == 0) if pd.notna(xo) else 0.0
    a = C["avail"].clip(1e-4, 1 - 1e-4)
    f["c_avail_logit"] = np.log(a / (1 - a))
    md = [[dd for dd in meet_dates.get((X, c), []) if dd < t] for c in C.index]
    f["rematch"] = [float(len(m) > 0) for m in md]
    f["c_beat_x_before"] = [float(any((not w) for dd, w in zip(meet_dates.get((X, c), []), meet_won.get((X, c), []))
                                      if dd < t)) for c in C.index]
    f["streak_gap"] = (C["streak"] - x["streak"]).abs()
    f["both_won_last"] = C["last_win"] * x["last_win"]
    f["c_lost_last"] = 1 - C["last_win"] - C["last_nodecision"]
    f["log_n_gap"] = (C["log_n"] - x["log_n"]).abs()
    f["c_debut_only"] = C["debut_only"]
    ag = (C["age"] - x["age"]).abs() if pd.notna(x["age"]) else pd.Series(np.nan, index=C.index)
    f["age_gap"] = (ag.fillna(ag.median() if ag.notna().any() else 4.0) / 5.0)
    f["log_days_gap"] = (C["log_days"] - x["log_days"]).abs()
    f["candidate"] = C.index
    f["raw_rank_gap"] = gap.abs().to_numpy()
    f["avail"] = C["avail"].to_numpy()
    return f


# ---------- conditional logit ----------
def fit_clogit(X: np.ndarray, y: np.ndarray, groups: np.ndarray, l2: float = 1.0) -> np.ndarray:
    starts = np.r_[0, np.flatnonzero(np.diff(groups)) + 1]
    has = np.add.reduceat(y, starts) > 0

    def f(w):
        s = X @ w
        mx = np.maximum.reduceat(s, starts)
        e = np.exp(s - np.repeat(mx, np.diff(np.r_[starts, len(s)])))
        z = np.add.reduceat(e, starts)
        lse = mx + np.log(z)
        ll = (np.add.reduceat(s * y, starts) - lse)[has].sum()
        p = e / np.repeat(z, np.diff(np.r_[starts, len(s)]))
        rep = np.repeat(has, np.diff(np.r_[starts, len(s)]))
        g = X.T @ ((y - p) * rep)
        return -ll + 0.5 * l2 * w @ w, -g + l2 * w

    return minimize(f, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B").x


def _positions(df: pd.DataFrame, score: str) -> pd.Series:
    """Position (1 = top) of the real opponent in each query's list, NaN when he is not in the pool."""
    d = df[["qid", score, "target"]].copy()
    d["pos"] = d.groupby("qid")[score].rank(ascending=False, method="first")
    return d[d["target"] == 1].set_index("qid")["pos"]


def _metrics(pos: pd.Series, qids: pd.Index) -> dict:
    p = pos.reindex(qids)
    out = {f"top{k}": round(float((p <= k).mean()), 4) for k in TOPK}
    out["mrr"] = round(float((1 / p).fillna(0).mean()), 4)
    out["queries"] = int(len(qids))
    return out


def evaluate(n_boot: int = 2000, seed: int = 5) -> dict:
    bouts = _bouts()
    P = prepare_panel(AV.load_panel(), bouts)
    pairs, queries = build_queries(P, bouts, TRAIN_BOUTS[0], TEST_BOUTS[1])
    queries["test"] = queries["date"] >= TEST_BOUTS[0]
    pairs = pairs.merge(queries[["qid", "test"]], on="qid")
    tr, te = pairs[~pairs["test"]].copy(), pairs[pairs["test"]].copy()
    mu, sd = tr[PAIR_FEATURES].mean(), tr[PAIR_FEATURES].std().replace(0, 1)
    tr = tr.sort_values("qid", kind="stable")
    w = fit_clogit(((tr[PAIR_FEATURES] - mu) / sd).to_numpy(), tr["target"].to_numpy(), tr["qid"].to_numpy())
    te["M"] = ((te[PAIR_FEATURES] - mu) / sd).to_numpy() @ w
    rng0 = np.random.default_rng(0)
    te["R1"] = -te["raw_rank_gap"] + 1e-6 * rng0.random(len(te))
    te["R2"] = -np.log1p(te["raw_rank_gap"]) + np.log(te["avail"].clip(1e-4))
    TQ = queries[queries["test"]]
    sets = {"all_test_bouts": TQ["qid"], "eligible_only": TQ.loc[TQ["status"] == "eligible", "qid"]}
    res = {"train_queries": int((~queries["test"]).sum()),
           "train_eligible": int(((~queries["test"]) & (queries["status"] == "eligible")).sum()),
           "test_coverage": TQ["status"].value_counts().to_dict(),
           "test_median_pool": float(TQ["pool_size"].median()), "models": {}}
    pos = {m: _positions(te, m) for m in ("R1", "R2", "M")}
    for name, q in sets.items():
        res["models"][name] = {m: _metrics(pos[m], pd.Index(q)) for m in pos}
    # paired bootstrap over event months, eligible queries, MRR and top-15
    E = TQ[TQ["status"] == "eligible"].set_index("qid")
    E["month"] = E["date"].dt.to_period("M")
    rng = np.random.default_rng(seed)
    months = E["month"].unique()
    groups = {m: E.index[E["month"] == m] for m in months}
    for b in ("R1", "R2"):
        for metric, fn in (("mrr", lambda p: (1 / p).fillna(0)), ("top15", lambda p: (p <= 15).astype(float))):
            dm = fn(pos["M"].reindex(E.index)) - fn(pos[b].reindex(E.index))
            s = np.array([dm[groups[m]].sum() for m in months])
            c = np.array([len(groups[m]) for m in months])
            draws = [s[i].sum() / c[i].sum() for i in (rng.integers(0, len(s), len(s)) for _ in range(n_boot))]
            res[f"M_minus_{b}_{metric}"] = {"mean": round(float(s.sum() / c.sum()), 4),
                                           "ci95": [round(float(np.percentile(draws, 2.5)), 4),
                                                    round(float(np.percentile(draws, 97.5)), 4)]}
    by_year = []
    for yv, g in TQ.groupby(TQ["date"].dt.year):
        by_year.append({"year": int(yv), **_metrics(pos["M"], pd.Index(g["qid"]))})
    res["M_by_year_all_bouts"] = by_year
    res["coefficients_std"] = {k: round(float(v), 4) for k, v in zip(PAIR_FEATURES, w)}
    # face validity: the ten highest-profile test queries (both fighters officially ranked)
    te_q = te.merge(TQ[["qid", "date", "fighter", "opponent"]], on="qid")
    te_q["pos_M"] = te_q.groupby("qid")["M"].rank(ascending=False, method="first")
    top = te_q[(te_q["both_off_ranked"] == 1) & (te_q["target"] == 1)].sort_values("date").tail(12)
    res["examples"] = []
    for _, r in top.iterrows():
        lst = te_q[te_q["qid"] == r["qid"]].sort_values("M", ascending=False)["candidate"].head(5).tolist()
        res["examples"].append({"date": str(r["date"].date()), "fighter": r["fighter"], "actual": r["opponent"],
                                "position": int(r["pos_M"]), "model_top5": lst})
    OUT.mkdir(parents=True, exist_ok=True)
    te_q[["qid", "date", "fighter", "opponent", "candidate", "M", "pos_M", "target"]].to_csv(
        OUT / "pairing_test_lists.csv.gz", index=False)
    queries.to_csv(OUT / "pairing_queries.csv.gz", index=False)
    return res


def current_lists(as_of: str, k: int = 15) -> pd.DataFrame:
    """Deployable top-k next-opponent lists for every fighter active on `as_of` (a month start). The pairing model is
    refitted on every query from 2015 through the last fully known bouts; nothing dated on or after `as_of` is used."""
    as_of = pd.Timestamp(as_of)
    bouts = _bouts()
    hist = AV.load_panel()
    now = AV.build_panel(bouts=bouts.assign(date=bouts["date"].dt.strftime("%Y-%m-%d")), start=str(as_of.date()),
                         end=str(as_of.date()))
    P = prepare_panel(pd.concat([hist, now], ignore_index=True), bouts)
    pairs, queries = build_queries(P[P["snapshot"] < as_of], bouts[bouts["date"] < as_of], TRAIN_BOUTS[0],
                                   str((as_of - pd.Timedelta(days=1)).date()))
    pairs = pairs.sort_values("qid", kind="stable")
    mu, sd = pairs[PAIR_FEATURES].mean(), pairs[PAIR_FEATURES].std().replace(0, 1)
    w = fit_clogit(((pairs[PAIR_FEATURES] - mu) / sd).to_numpy(), pairs["target"].to_numpy(), pairs["qid"].to_numpy())
    hb = bouts[bouts["date"] < as_of]
    h2 = pd.concat([pd.DataFrame({"fighter": hb["fighter_a"], "opp": hb["fighter_b"], "date": hb["date"],
                                  "won": hb["result_a"] == 1}),
                    pd.DataFrame({"fighter": hb["fighter_b"], "opp": hb["fighter_a"], "date": hb["date"],
                                  "won": hb["result_a"] == 0})])
    g = h2.groupby(["fighter", "opp"])
    md, mw = g["date"].apply(list).to_dict(), g["won"].apply(list).to_dict()
    S = P[P["snapshot"] == as_of].set_index("fighter")
    rows = []
    for X, x in S.iterrows():
        pool = S[(S["home"] == x["home"]) & (S.index != X)]
        if pool.empty:
            continue
        f = _pair_features(X, x, pool, as_of, md, mw)
        sc = ((f[PAIR_FEATURES] - mu) / sd).to_numpy() @ w
        pr = np.exp(sc - logsumexp(sc))
        order = np.argsort(-sc)[:k]
        for pos, i in enumerate(order, 1):
            rows.append({"as_of": as_of.date(), "fighter": X, "division": x["home"],
                         "fighter_avail_120d": round(float(x["avail"]), 3), "position": pos,
                         "candidate": f["candidate"].iloc[i], "share": round(float(pr[i]), 4),
                         "candidate_avail_120d": round(float(f["avail"].iloc[i]), 3),
                         "candidate_official_rank": pool["off_rank"].iloc[i]})
    return pd.DataFrame(rows)


def main() -> None:
    res = evaluate()
    (OUT / "pairing_backtest.json").write_text(json.dumps(res, indent=1, default=str))
    print("coverage:", res["test_coverage"], "median pool", res["test_median_pool"])
    for s, d in res["models"].items():
        print(s)
        for m, v in d.items():
            print("  ", m, v)
    for k, v in res.items():
        if k.startswith("M_minus"):
            print(k, v)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--lists":
        L = current_lists(sys.argv[2])
        path = OUT / f"next_opponents_{sys.argv[2]}.csv"
        L.to_csv(path, index=False)
        print(f"{path}: {L['fighter'].nunique()} fighters")
    else:
        main()
