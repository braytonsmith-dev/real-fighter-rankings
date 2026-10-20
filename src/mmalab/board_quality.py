"""
board_quality.py - Quality tests for a resume board, reported every week and never fitted to.

A resume board ranks who has earned the spot as of now, not who wins next, so predictive concordance is a descriptive
check rather than its objective (PREREGISTRATION.md section 8). These are the board's own tests, the product
endpoints of PREREGISTRATION.md section 5, computed for the registered board and for every shadow version:

  turnover            share of top-15 slots whose holder changed since the previous snapshot
  moves_without_bout  fighters who moved more than three places since the previous snapshot without fighting
  h2h_conflicts       pairs where the lower-ranked fighter beat the higher-ranked one in the head-to-head window
                      and the rule did not lift him (the gap exceeded the allowance, the win was an old close one,
                      or the winner's last five is negative), listed so a reader can judge each one
  band_outliers       published ranks outside their own weight band (should be none since Oct 1, 2026)
  overrides_recent    dated roster facts added in the last seven days
  external_agreement  mean absolute gap and top-10 overlap against each public board (from compare.py)

    PYTHONPATH=src python3 -m mmalab.board_quality        # writes outputs/board_quality.json (and one per shadow version)
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.rankings import RANKED_DIVISIONS
from mmalab.resume_board import last_five

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
PROC = ROOT / "data" / "processed"
CFG = ROOT / "config"
DATED_FILES = ("layoffs.yaml", "roster_exclusions.yaml", "division_overrides.yaml", "reserved.yaml", "interim_champions.yaml", "short_notice.yaml")


def _positions(board: pd.DataFrame) -> dict[tuple[str, str], int]:
    pos = {}
    for r in board.itertuples():
        p = 0 if (getattr(r, "champion", False) or getattr(r, "interim", False) or getattr(r, "reserved", False)) else int(r.rank)
        pos[(r.division, r.fighter)] = p
    return pos


def previous_snapshot(history_root: Path, before: pd.Timestamp) -> tuple[pd.DataFrame | None, pd.Timestamp | None]:
    snaps = sorted(history_root.glob("board_*.csv"))
    prior = [p for p in snaps if pd.Timestamp(p.stem.split("_")[1]) < before]
    if not prior:
        return None, None
    p = prior[-1]
    return pd.read_csv(p), pd.Timestamp(p.stem.split("_")[1])


def h2h_conflicts(board: pd.DataFrame, bouts: pd.DataFrame, as_of: pd.Timestamp, max_years: float = 3.0) -> list[dict]:
    """Lower-ranked fighter beat the higher-ranked one in the window, and still sits below him."""
    pos = _positions(board)
    d = bouts[bouts["result_a"].isin([0.0, 1.0]) & ((as_of - bouts["date"]).dt.days <= max_years * 365.25)].sort_values("date")
    lf = last_five(bouts[bouts["date"] <= as_of])
    negative = set(lf.index[lf["last5"].apply(lambda r: int(r.split("-")[1]) > int(r.split("-")[0]))])
    last_meeting: dict[tuple[str, str], tuple[pd.Timestamp, str, bool]] = {}
    for x in d.itertuples():
        key = tuple(sorted((x.fighter_a, x.fighter_b)))
        winner = x.fighter_a if x.result_a == 1.0 else x.fighter_b
        last_meeting[key] = (x.date, winner, bool(getattr(x, "close", False)) if "close" in d.columns else False)
    out = []
    for (f1, f2), (date, winner, close) in last_meeting.items():
        loser = f2 if winner == f1 else f1
        for div in RANKED_DIVISIONS:
            pw, pl = pos.get((div, winner)), pos.get((div, loser))
            if pw is None or pl is None or pw == 0 or pl == 0:
                continue
            if pw > pl:
                why = ("winner's last five is negative" if winner in negative else
                       "close win more than a year old" if close and (as_of - date).days > 365 else
                       f"gap {pw - pl} exceeds the rule's allowance")
                out.append({"division": div, "winner": winner, "winner_rank": pw, "loser": loser, "loser_rank": pl,
                            "won_on": str(date.date()), "left_as_is_because": why})
    return sorted(out, key=lambda r: (r["division"], r["loser_rank"]))


def quality(board: pd.DataFrame, history_root: Path, bouts: pd.DataFrame, as_of: pd.Timestamp, label: str) -> dict:
    prev, prev_date = previous_snapshot(history_root, as_of)
    res: dict = {"version": label, "as_of": str(as_of.date()), "previous_snapshot": str(prev_date.date()) if prev_date is not None else None}
    top = board[(board["rank"] >= 1) & (board["rank"] <= 15)]
    if prev is not None:
        ppos = {(r.division, r.fighter): int(r.position) for r in prev.itertuples()}
        prev_top = {(r.division, r.fighter) for r in prev.itertuples() if 1 <= int(r.position) <= 15}
        now_top = {(r.division, r.fighter) for r in top.itertuples()}
        res["turnover"] = {"top15_slots": len(now_top), "new_holders": len(now_top - prev_top),
                           "share": round(len(now_top - prev_top) / max(len(now_top), 1), 3)}
        fought = set()
        window = bouts[(bouts["date"] > prev_date) & (bouts["date"] <= as_of)]
        fought |= set(window["fighter_a"]) | set(window["fighter_b"])
        moves = []
        for r in board.itertuples():
            p0 = ppos.get((r.division, r.fighter))
            p1 = 0 if (r.champion or getattr(r, "interim", False) or getattr(r, "reserved", False)) else int(r.rank)
            if p0 is None or p0 == 0 or p1 == 0 or r.fighter in fought:
                continue
            if abs(p1 - p0) > 3 and min(p0, p1) <= 30:
                moves.append({"division": r.division, "fighter": r.fighter, "from": p0, "to": p1})
        res["moves_without_bout"] = {"count": len(moves), "fighters": sorted(moves, key=lambda m: -abs(m["to"] - m["from"]))[:25]}
    conflicts = h2h_conflicts(board, bouts, as_of)
    res["h2h_conflicts"] = {"count": len(conflicts), "within_top15": sum(1 for c in conflicts if c["loser_rank"] <= 15), "pairs": conflicts[:40]}
    if {"rank_p10", "rank_p90"} <= set(board.columns):
        ranked = board[board["rank"] >= 1]
        outside = ranked[(ranked["rank"] < ranked["rank_p10"]) | (ranked["rank"] > ranked["rank_p90"])]
        res["band_outliers"] = {"count": int(len(outside)), "fighters": [f"{r.division}: {r.fighter} #{int(r.rank)} band {int(r.rank_p10)}-{int(r.rank_p90)}" for r in outside.itertuples()][:20]}
    recent = []
    for name in DATED_FILES:
        p = CFG / name
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text()) or []
        if isinstance(data, list):
            for e in data:
                if isinstance(e, dict):
                    since = e.get("since") or e.get("date")
                    try:
                        if since is not None and (as_of - pd.Timestamp(since)).days <= 7:
                            recent.append(f"{name}: {e.get('fighter') or e.get('division')} since {since}")
                    except (TypeError, ValueError):
                        pass
    res["overrides_recent"] = {"count": len(recent), "entries": recent}
    pw = OUT / "compare_pairwise.csv"
    if pw.exists():
        pairs = pd.read_csv(pw)
        ours = pairs[(pairs["a"] == "Our board") | (pairs["b"] == "Our board")]
        res["external_agreement"] = [{"board": r.a if r.b == "Our board" else r.b, "shared": int(r.shared), "mean_abs_gap": float(r.mean_abs_gap),
                                      "top10_overlap": float(r.top10_overlap_pct)} for r in ours.itertuples()]
    return res


def main() -> None:
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    reports = []
    board = pd.read_csv(OUT / "composite_rankings_full.csv")
    as_of = bouts["date"].max()
    r = quality(board, OUT / "history", bouts, as_of, "v1.0")
    (OUT / "board_quality.json").write_text(json.dumps(r, indent=2, default=str))
    reports.append(r)
    try:
        from mmalab.board_versions import load_version, version_files
        for p in version_files():
            v = load_version(p)
            bp = v["board_root"] / "composite_rankings_full.csv"
            if v.get("label") in ("shadow", "candidate") and bp.exists():
                rv = quality(pd.read_csv(bp), v["history_root"], bouts, as_of, f"v{v['version']}")
                (v["board_root"] / "board_quality.json").write_text(json.dumps(rv, indent=2, default=str))
                reports.append(rv)
    except ImportError:
        pass
    for r in reports:
        t = r.get("turnover", {})
        print(f"{r['version']}: turnover {t.get('share', 'n/a')} ({t.get('new_holders', '-')} new top-15 holders), moves without a bout "
              f"{r.get('moves_without_bout', {}).get('count', 'n/a')}, head-to-head conflicts {r['h2h_conflicts']['count']} "
              f"({r['h2h_conflicts']['within_top15']} in a top 15), band outliers {r.get('band_outliers', {}).get('count', 'n/a')}, "
              f"recent roster facts {r['overrides_recent']['count']}")


if __name__ == "__main__":
    main()
