"""
board_versions.py - Shadow board versions built beside the registered v1.0 board.

PREREGISTRATION.md section 9 lets a new board version be developed at any time as long as it is published under
its own label and never substituted for v1.0 during the registered period. This module does that mechanically:

  config/board_v<major>_<minor>.yaml   the version's overrides over config/weights.yaml (which stays frozen)
  outputs/boards/v<version>/            the version's board files, same layout as outputs/
  outputs/history_v<version>/           the version's own snapshots, so its forward record is kept apart
  outputs/forward_validation_v<version>.{csv,json}   its forward validation, scored exactly like v1.0's

    PYTHONPATH=src python3 -m mmalab.board_versions                 # build every shadow version for today
    PYTHONPATH=src python3 -m mmalab.board_versions --backfill 36   # reconstruct the last 36 months of event-eve boards
                                                                   # (retrospective, in-sample; labelled as such)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab import resume_board
from mmalab.history import snapshot, validate
from mmalab.rankings import RANKED_DIVISIONS

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"
OUT = ROOT / "outputs"
PROC = ROOT / "data" / "processed"


def version_files() -> list[Path]:
    return sorted(CFG.glob("board_v*_*.yaml"))


def load_version(path: Path) -> dict:
    v = yaml.safe_load(path.read_text())
    v["path"] = path
    v["suffix"] = "_v" + str(v["version"]).replace(".", "_")
    v["history_root"] = ROOT / v.get("history_dir", f"outputs/history_v{v['version']}")
    v["board_root"] = ROOT / v.get("board_dir", f"outputs/boards/v{v['version']}")
    return v


def build_version(v: dict, as_of: str | None = None, stability: bool = True) -> tuple[pd.DataFrame, dict]:
    return resume_board.build(as_of=as_of, stability=stability, overrides=v.get("overrides") or {})


def write_board(board: pd.DataFrame, meta: dict, v: dict) -> None:
    """Same files resume_board.main() writes, in the version's own directory."""
    root = v["board_root"]
    root.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((CFG / "weights.yaml").read_text())
    board.to_csv(root / "composite_rankings_full.csv", index=False)
    size = cfg["board_size"]
    top = board[board["rank"] <= size]
    cols = ["division", "rank", "fighter", "champion", "interim", "reserved", "score", "rating", "quality_wins",
            "top10_wins_15y", "top15_wins_15y", "entrenched", "last5", "streak", "days_since", "injury", "ko_risk",
            "rank_p10", "rank_p90"]
    top[cols].round(3).to_csv(root / "composite_top15_by_division.csv", index=False)
    audit_cols = ["division", "rank", "fighter", "placement", "division_source", "score", "rating_term",
                  "ledger_term", "form_penalty", "rating", "rating_raw", "inactivity_penalty", "injury",
                  "quality_wins", "ledger_detail", "top10_wins_15y", "top15_wins_15y", "entrenched", "last5", "streak",
                  "days_since", "ko_risk", "rank_p10", "rank_p90"]
    top[[c for c in audit_cols if c in top.columns]].round(3).to_csv(root / "audit_top30.csv", index=False)
    lines = [f"# Divisional boards, REAL v{v['version']} ({v.get('label', 'shadow')}) as of {meta['as_of'].date()}",
             f"overrides over weights.yaml: {json.dumps(v.get('overrides') or {}, sort_keys=True)}", ""]
    for div in RANKED_DIVISIONS:
        g = top[top["division"] == div]
        if g.empty:
            continue
        lines.append(f"\n## {div}")
        for r in g.itertuples():
            label = " C" if r.champion else ("IC" if r.interim else (" R" if r.reserved else f"{r.rank:>2}"))
            lines.append(f"{label}. {r.fighter:<26} score {r.score:+.2f}  rating {r.rating:6.0f}  last5 {r.last5:<4} "
                         f"ledger {r.quality_wins:4.1f}  form -{r.form_penalty:.2f}  band [{int(r.rank_p10)}-{int(r.rank_p90)}]")
    lines += ["", "## Placement rules applied"] + [f"- {n}" for n in meta["h2h"]]
    (root / "composite_boards.md").write_text("\n".join(lines))


def compare_to_registered(board: pd.DataFrame, v: dict) -> dict:
    """How the shadow board differs from the registered board built from the same data."""
    reg_path = OUT / "composite_rankings_full.csv"
    if not reg_path.exists():
        return {}
    reg = pd.read_csv(reg_path)
    m = reg[["division", "fighter", "rank"]].merge(board[["division", "fighter", "rank"]], on=["division", "fighter"],
                                                    how="outer", suffixes=("_v10", "_new"))
    top = m[(m["rank_v10"] <= 15) | (m["rank_new"] <= 15)].copy()
    top["move"] = top["rank_new"] - top["rank_v10"]
    changed = top[top["rank_v10"] != top["rank_new"]].dropna()
    biggest = changed.assign(a=changed["move"].abs()).sort_values("a", ascending=False).head(15)
    res = {"top15_slots_compared": int(len(top)), "top15_slots_changed": int((top["rank_v10"] != top["rank_new"]).sum()),
           "largest_moves": [{"division": r.division, "fighter": r.fighter, "v1.0": int(r.rank_v10), f"v{v['version']}": int(r.rank_new)}
                             for r in biggest.itertuples()]}
    (v["board_root"] / "diff_vs_v1_0.json").write_text(json.dumps(res, indent=2))
    return res


def fit_slope(root: Path) -> float | None:
    """One-parameter logistic map fitted on this version's own retrospective snapshots (the v1.0 slope 1.36 was fitted
    the same way on Oct 1, 2026). Returns None until at least 200 bouts exist."""
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    snaps = sorted(root.glob("board_*.csv"))
    diffs, ys = [], []
    for i, p in enumerate(snaps):
        t0 = pd.Timestamp(p.stem.split("_")[1])
        t1 = pd.Timestamp(snaps[i + 1].stem.split("_")[1]) if i + 1 < len(snaps) else pd.Timestamp.max
        b = pd.read_csv(p)
        info = {(r.division, r.fighter): float(r.score) for r in b.itertuples()}
        w = bouts[(bouts["date"] > t0) & (bouts["date"] <= t1) & bouts["result_a"].isin([0.0, 1.0])]
        for x in w.itertuples():
            a, c = info.get((x.division, x.fighter_a)), info.get((x.division, x.fighter_b))
            if a is None or c is None:
                continue
            diffs.append(a - c)
            ys.append(float(x.result_a))
    if len(ys) < 200:
        return None
    d, y = np.array(diffs), np.array(ys)

    def ll(s: float) -> float:
        pr = np.clip(1 / (1 + np.exp(-np.clip(s * d, -30, 30))), 1e-6, 1 - 1e-6)
        return float(-np.mean(y * np.log(pr) + (1 - y) * np.log(1 - pr)))
    lo, hi = 0.05, 10.0
    gr = (math.sqrt(5) - 1) / 2
    c1, c2 = hi - gr * (hi - lo), lo + gr * (hi - lo)
    for _ in range(60):
        if ll(c1) < ll(c2):
            hi = c2
        else:
            lo = c1
        c1, c2 = hi - gr * (hi - lo), lo + gr * (hi - lo)
    return round((lo + hi) / 2, 2)


def slope_for(v: dict) -> float:
    """The version's frozen probability slope: recorded in its config the first time it can be fitted."""
    if v.get("prob_slope"):
        return float(v["prob_slope"])
    s = fit_slope(v["history_root"])
    if s is None:
        return 1.36
    text = v["path"].read_text()
    text += f"\nprob_slope: {s}   # fitted on this version's retrospective snapshots on {pd.Timestamp.today().date()}; frozen from then on\n"
    v["path"].write_text(text)
    v["prob_slope"] = s
    return s


def backfill(v: dict, months: int) -> list[Path]:
    """Event-eve reconstructions for the last `months`, into the version's own history directory. These are
    retrospective (built with rules chosen after the bouts) and are labelled that way by validate()."""
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    last = bouts["date"].max()
    events = sorted(bouts.loc[bouts["date"] > last - pd.DateOffset(months=months), "date"].unique())
    paths = []
    for ev in events:
        board, meta = build_version(v, as_of=str(pd.Timestamp(ev).date()), stability=False)
        paths.append(snapshot(board, pd.Timestamp(ev) - pd.Timedelta(days=1), root=v["history_root"]))
    return paths


def main(backfill_months: int | None = None) -> None:
    for path in version_files():
        v = load_version(path)
        if v.get("label") not in ("shadow", "candidate"):
            continue
        if backfill_months:
            n = len(backfill(v, backfill_months))
            print(f"v{v['version']}: {n} retrospective snapshots written to {v['history_root'].relative_to(ROOT)}")
        board, meta = build_version(v)
        write_board(board, meta, v)
        snapshot(board, meta["as_of"], root=v["history_root"])
        diff = compare_to_registered(board, v)
        slope = slope_for(v)
        res = validate(root=v["history_root"], freeze_date=pd.Timestamp(v["since"]), slope=slope, suffix=v["suffix"],
                       label=f"v{v['version']}")
        pro = res.get("prospective_since_freeze", {}).get("primary_both_scored", {})
        print(f"v{v['version']} ({v.get('label')}): board written to {v['board_root'].relative_to(ROOT)}; "
              f"top-15 slots changed vs v1.0: {diff.get('top15_slots_changed')}/{diff.get('top15_slots_compared')}; "
              f"slope {slope}; prospective bouts {pro.get('bouts', 0)}")


if __name__ == "__main__":
    months = None
    if "--backfill" in sys.argv:
        i = sys.argv.index("--backfill")
        months = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 36
    main(months)
