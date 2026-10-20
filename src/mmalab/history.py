"""
history.py - Board snapshots, movement arrows and the validation ledger.

  snapshot(board, as_of)  -> outputs/history/board_<as_of>.csv
  backfill(months)        -> rebuilds the board as it stood the day before each event
                             in the last `months` and saves each snapshot
  validate()              -> one row per bout between two fighters who both appear in the
                             snapshot before that bout (the primary population in
                             PREREGISTRATION.md), with every frozen baseline on the same bout.
Writes outputs/forward_validation.csv and outputs/forward_validation.json. Bouts on or before
the v1.0 freeze date are a retrospective reconstruction; bouts after it are the prospective test.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from mmalab import resume_board
from mmalab.official_ranks import OfficialRanks

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
HIST = OUT / "history"
PROC = ROOT / "data" / "processed"

FREEZE_DATE = pd.Timestamp("2026-10-01")   # VERSION file; bouts after this date are prospective
PROB_SLOPE = 1.36                           # frozen score-difference -> win probability map (PREREGISTRATION.md section 5)


def board_position(row) -> int:
    if row["champion"]:
        return 0
    if row.get("interim", False) or row.get("reserved", False):
        return 0
    return int(row["rank"])


def snapshot(board: pd.DataFrame, as_of: pd.Timestamp, root: Path | None = None) -> Path:
    """Write one board snapshot. `root` defaults to outputs/history (the registered v1.0 board); shadow versions
    pass their own directory so the two forward records never mix."""
    root = Path(root) if root is not None else HIST
    root.mkdir(parents=True, exist_ok=True)
    b = board.copy()
    b["position"] = b.apply(board_position, axis=1)
    path = root / f"board_{pd.Timestamp(as_of).date()}.csv"
    b[["division", "fighter", "position", "rank", "score"]].to_csv(path, index=False)
    return path


def backfill(months: int = 12) -> list[Path]:
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    last = bouts["date"].max()
    events = sorted(bouts.loc[bouts["date"] > last - pd.DateOffset(months=months), "date"].unique())
    paths = []
    for ev in events:
        board, meta = resume_board.build(as_of=str(pd.Timestamp(ev).date()), stability=False)
        paths.append(snapshot(board, pd.Timestamp(ev) - pd.Timedelta(days=1)))
    board, meta = resume_board.build(stability=False)
    paths.append(snapshot(board, meta["as_of"]))
    return paths


def previous_positions(before: pd.Timestamp, root: Path | None = None) -> dict:
    """Positions from the latest snapshot strictly before `before`."""
    root = Path(root) if root is not None else HIST
    snaps = sorted(root.glob("board_*.csv"))
    prior = [p for p in snaps if pd.Timestamp(p.stem.split("_")[1]) < pd.Timestamp(before)]
    if not prior:
        return {}
    d = pd.read_csv(prior[-1])
    return {(r.division, r.fighter): int(r.position) for r in d.itertuples()}


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 3), round(c + h, 3)]


def _scores(df: pd.DataFrame, col: str, y: np.ndarray) -> dict | None:
    p = df[col].to_numpy(dtype=float)
    ok = ~np.isnan(p)
    if ok.sum() == 0:
        return None
    p, yy = np.clip(p[ok], 1e-6, 1 - 1e-6), y[ok]
    return {"n": int(ok.sum()),
            "log_loss": round(float(-np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p))), 4),
            "brier": round(float(np.mean((p - yy) ** 2)), 4),
            "accuracy": round(float(np.mean((p > 0.5) == (yy == 1))), 4)}


def _summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"bouts": 0}
    y = df["result_a"].to_numpy(dtype=float)
    conc = df["real_concordant"].to_numpy(dtype=float)
    k = float(np.nansum(conc))
    out = {"bouts": int(len(df)),
           "real_concordance": round(k / len(df), 3), "real_concordance_wilson95": wilson(int(round(k)), len(df)),
           "real_probability": _scores(df, "p_real", y),
           "results_only_elo": _scores(df, "p_classic", y),
           "performance_adjusted_elo": _scores(df, "p_predictive", y)}
    both = df.dropna(subset=["official_correct"])
    if len(both):
        oc = int(both["official_correct"].astype(float).sum())
        rc = float(both["real_concordant"].sum())
        out["official_board"] = {"bouts_both_ranked": int(len(both)),
                                 "official_concordance": round(oc / len(both), 3),
                                 "official_wilson95": wilson(oc, len(both)),
                                 "real_concordance_same_bouts": round(rc / len(both), 3)}
    return out


def validate(root: Path | None = None, freeze_date: pd.Timestamp | None = None, slope: float | None = None,
             suffix: str = "", label: str = "v1.0") -> dict:
    """Score every snapshot in `root` against the bouts that followed it. The defaults are the registered v1.0 board;
    a shadow version passes its own snapshot directory, first-snapshot date, probability slope and file suffix."""
    root = Path(root) if root is not None else HIST
    freeze_date = pd.Timestamp(freeze_date) if freeze_date is not None else FREEZE_DATE
    slope = float(slope) if slope is not None else PROB_SLOPE
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    snaps = sorted(root.glob("board_*.csv"))
    names = pd.concat([bouts["fighter_a"], bouts["fighter_b"]]).dropna().unique().tolist()
    off = OfficialRanks(names)
    pred, classic = {}, {}
    rated_path = PROC / "bouts_rated.csv"
    if rated_path.exists():
        rr = pd.read_csv(rated_path)
        pred = dict(zip(rr["bout_url"], rr["p_a"]))
        if "p_a_classic" in rr.columns:
            classic = dict(zip(rr["bout_url"], rr["p_a_classic"]))
    rows = []
    for i, p in enumerate(snaps):
        t0 = pd.Timestamp(p.stem.split("_")[1])
        t1 = pd.Timestamp(snaps[i + 1].stem.split("_")[1]) if i + 1 < len(snaps) else pd.Timestamp.max
        board = pd.read_csv(p)
        info = {(r.division, r.fighter): (int(r.position), float(r.score)) for r in board.itertuples()}
        window = bouts[(bouts["date"] > t0) & (bouts["date"] <= t1) & bouts["result_a"].isin([0.0, 1.0])]
        for x in window.itertuples():
            a, b = info.get((x.division, x.fighter_a)), info.get((x.division, x.fighter_b))
            if a is None or b is None:
                continue
            (pa, sa), (pb, sb) = a, b
            diff = sa - sb
            # concordance uses the published order: champion (0) first, then rank; two title holders tie at 0.5
            concordant = 0.5 if pa == pb else float((pa < pb) == (x.result_a == 1.0))
            p_real = 1.0 / (1.0 + math.exp(-slope * diff))
            oa, ob = off.rank(x.fighter_a, x.division, x.date), off.rank(x.fighter_b, x.division, x.date)
            off_right = None
            if oa is not None and ob is not None and oa != ob and max(oa, ob) < 99:
                off_right = float((oa < ob) == (x.result_a == 1.0))
            top = lambda n: (1 <= pa <= n or pa == 0) and (1 <= pb <= n or pb == 0)
            rows.append({"snapshot": t0.date(), "date": x.date.date(), "prospective": x.date > freeze_date,
                         "division": x.division, "title_fight": bool(x.title_fight),
                         "fighter_a": x.fighter_a, "pos_a": pa, "score_a": round(sa, 4),
                         "fighter_b": x.fighter_b, "pos_b": pb, "score_b": round(sb, 4),
                         "result_a": float(x.result_a), "winner": x.fighter_a if x.result_a == 1.0 else x.fighter_b,
                         "real_concordant": concordant, "p_real": round(p_real, 4),
                         "both_top30": top(30), "both_top15": top(15),
                         "official_a": oa, "official_b": ob, "official_correct": off_right,
                         "p_predictive": pred.get(x.bout_url, np.nan), "p_classic": classic.get(x.bout_url, np.nan),
                         "method": x.method})
    df = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / f"forward_validation{suffix}.csv", index=False)
    res = {"version": label, "snapshots": len(snaps), "freeze_date": str(freeze_date.date()), "probability_map_slope": slope,
           "protocol": "PREREGISTRATION.md"}
    if not df.empty:
        for label, mask in (("retrospective_reconstruction", ~df["prospective"]), ("prospective_since_freeze", df["prospective"])):
            part = df[mask]
            res[label] = {"primary_both_scored": _summary(part),
                          "secondary_both_top30": _summary(part[part["both_top30"]]),
                          "secondary_both_top15": _summary(part[part["both_top15"]]),
                          "secondary_title_fights": _summary(part[part["title_fight"]])}
    res["note"] = (f"Snapshots before the freeze were rebuilt with the {label} rules, so the retrospective block is an "
                   "in-sample reconstruction; only the prospective block is the pre-registered test.")
    (OUT / f"forward_validation{suffix}.json").write_text(json.dumps(res, indent=2, default=str))
    return res


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        months = int(sys.argv[sys.argv.index("--backfill") + 1]) if len(sys.argv) > sys.argv.index("--backfill") + 1 else 12
        print(len(backfill(months)), "snapshots")
    print(json.dumps(validate(), indent=2, default=str))
