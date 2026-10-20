"""
checks.py - Sanity checks the weekly job runs after the rebuild and before it commits (audit finding E3).

    PYTHONPATH=src python3 -m mmalab.checks            # exit 1 and list every problem if anything is wrong
    PYTHONPATH=src python3 -m mmalab.checks --ref HEAD  # the git ref the append-only files are compared with

What is checked:
  data     bouts.csv has unique bout URLs, parseable dates no later than today, and at least as many rows as the
           committed copy (a refresh may add results, never lose them)
  boards   every ranked division has a board; ranks are 1..n without gaps; no NaN score, rating or rank; a champion
           or interim champion row, or a champions_override VACANT entry, per division; every top-15 fighter's last
           bout within the eligibility window
  history  no snapshot already in git has changed (PREREGISTRATION.md section 3: snapshots are never rewritten);
           the same for every shadow version's history directory
  picks    predictions/picks.csv is append-only: every row in the committed copy is still there with its lock
           fields unchanged; a graded row never changes grade again
  site     docs/index.html exists, carries the data date, and every local link in it resolves
A failing check stops the job before `git commit`, so a broken rebuild is reported by GitHub instead of published.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.rankings import RANKED_DIVISIONS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
LOCK_FIELDS = ["pick_id", "predicted_at_utc", "data_through", "model", "freeze_commit", "event_id", "event", "event_date",
               "division", "fighter_a", "fighter_b", "p_a", "pick", "confidence", "provisional", "p_a_classic", "pick_classic",
               "p_a_real", "pick_real", "p_a_v11", "pick_v11", "v11_locked_at_utc"]
FINAL_STATUSES = ("correct", "incorrect", "void", "no pick")


def git_show(path: str, ref: str) -> str | None:
    """Contents of `path` at `ref`, or None if it does not exist there."""
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def git_changed(prefix: str, ref: str) -> list[str]:
    """Tracked files under `prefix` that differ from `ref` (modified or deleted; additions are fine)."""
    r = subprocess.run(["git", "diff", "--name-status", ref, "--", prefix], cwd=ROOT, capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        status, _, name = line.partition("\t")
        if status and status[0] in "MD":
            out.append(f"{status[0]} {name}")
    return out


def check_data(ref: str) -> list[str]:
    p = ROOT / "data" / "processed" / "bouts.csv"
    probs = []
    if not p.exists():
        return ["data: data/processed/bouts.csv is missing"]
    b = pd.read_csv(p)
    dup = b["bout_url"].duplicated().sum()
    if dup:
        probs.append(f"data: {dup} duplicate bout URLs in bouts.csv")
    d = pd.to_datetime(b["date"], errors="coerce")
    if d.isna().any():
        probs.append(f"data: {int(d.isna().sum())} unparseable dates in bouts.csv")
    elif d.max().date() > date.today():
        probs.append(f"data: last bout date {d.max().date()} is in the future")
    old = git_show("data/processed/bouts.csv", ref)
    if old is not None:
        n_old = old.count("\n") - 1
        if len(b) < n_old:
            probs.append(f"data: bouts.csv shrank from {n_old} to {len(b)} rows")
    return probs


def check_boards(path: Path = OUT / "composite_rankings_full.csv", label: str = "boards") -> list[str]:
    probs = []
    if not path.exists():
        return [f"{label}: {path.relative_to(ROOT)} is missing"]
    b = pd.read_csv(path)
    for col in ("score", "rating", "rank"):
        if col not in b.columns:
            probs.append(f"{label}: column {col} missing")
        elif b[col].isna().any():
            probs.append(f"{label}: {int(b[col].isna().sum())} NaN values in {col}")
    override = yaml.safe_load((ROOT / "config" / "champions_override.yaml").read_text()) or {}
    vacant = {k for k, v in override.items() if str(v).upper().startswith("VACANT")}
    inact = yaml.safe_load((ROOT / "config" / "weights.yaml").read_text())["resume"]["inactivity"]
    for div in RANKED_DIVISIONS:
        g = b[b["division"] == div]
        if g.empty:
            probs.append(f"{label}: no rows for {div}")
            continue
        ranks = sorted(int(x) for x in g.loc[g["rank"] > 0, "rank"])
        if ranks != list(range(1, len(ranks) + 1)):
            probs.append(f"{label}: ranks are not 1..n in {div} (first gap near {next((i + 1 for i, r in enumerate(ranks) if r != i + 1), '?')})")
        if len(ranks) < 15:
            probs.append(f"{label}: only {len(ranks)} ranked fighters in {div}")
        titled = int(g["champion"].sum()) + int(g["interim"].sum()) if {"champion", "interim"} <= set(g.columns) else 0
        if titled == 0 and div not in vacant:
            probs.append(f"{label}: no champion or interim champion row in {div} and no VACANT override")
        if "days_since" in g.columns:
            top = g[(g["rank"] >= 1) & (g["rank"] <= 15)]
            limit = inact["injury_max_days"]
            late = top[top["days_since"] > limit]
            if not late.empty:
                probs.append(f"{label}: {', '.join(late['fighter'])} in the {div} top 15 with days_since over {limit}")
    return probs


def check_history(ref: str) -> list[str]:
    """A committed snapshot may change only while no bout has yet followed it (its event has not happened, so a
    data correction before the event is allowed); once a decided bout postdates it, it is frozen."""
    probs = []
    last_bout = None
    p = ROOT / "data" / "processed" / "bouts.csv"
    if p.exists():
        b = pd.read_csv(p, usecols=["date", "result_a"])
        dec = b[b["result_a"].isin([0.0, 0.5, 1.0])]
        last_bout = pd.to_datetime(dec["date"], errors="coerce").max() if len(dec) else None
    dirs = [OUT / "history"] + sorted(OUT.glob("history_v*"))
    for d in dirs:
        rel = str(d.relative_to(ROOT))
        changed = []
        for item in git_changed(rel, ref):
            name = Path(item.split(" ", 1)[1]).stem
            try:
                snap_date = pd.Timestamp(name.split("_")[1])
            except (IndexError, ValueError):
                changed.append(item)
                continue
            if item.startswith("D") or last_bout is None or last_bout > snap_date:
                changed.append(item)          # deleted, or already followed by a bout: frozen
        if changed:
            probs.append(f"history: {len(changed)} committed snapshot(s) in {rel} changed or disappeared after their event: {', '.join(changed[:5])}")
        for p in d.glob("board_*.csv"):
            if not re.fullmatch(r"board_\d{4}-\d{2}-\d{2}\.csv", p.name):
                probs.append(f"history: unexpected file name {p.name} in {rel}")
    return probs


def picks_problems(old: pd.DataFrame, new: pd.DataFrame) -> list[str]:
    """Append-only rules between the committed ledger `old` and the rebuilt ledger `new` (both as strings)."""
    probs = []
    if new["pick_id"].duplicated().any():
        probs.append("picks: duplicate pick_id in predictions/picks.csv")
    missing = set(old["pick_id"]) - set(new["pick_id"])
    if missing:
        probs.append(f"picks: {len(missing)} committed pick(s) removed: {', '.join(sorted(missing)[:5])}")
    o = old.drop_duplicates("pick_id").set_index("pick_id")
    n = new.drop_duplicates("pick_id").set_index("pick_id")
    common = o.index.intersection(n.index)
    for col in [c for c in LOCK_FIELDS if c in o.columns and c in n.columns and c != "pick_id"]:
        diff = common[(o.loc[common, col] != n.loc[common, col]).to_numpy()]
        # the shadow columns may be filled in once (empty -> value) after a lock; nothing else may change
        if col in ("p_a_v11", "pick_v11", "v11_locked_at_utc"):
            diff = diff[(o.loc[diff, col] != "").to_numpy()]
        if len(diff):
            probs.append(f"picks: lock field {col} changed on {len(diff)} committed row(s), e.g. {diff[0]}")
    if "status" in o.columns and "status" in n.columns:
        was_final = common[o.loc[common, "status"].isin(FINAL_STATUSES).to_numpy()]
        regraded = was_final[(o.loc[was_final, "status"] != n.loc[was_final, "status"]).to_numpy()]
        if len(regraded):
            probs.append(f"picks: {len(regraded)} graded row(s) changed grade, e.g. {regraded[0]}")
    return probs


def check_picks(ref: str) -> list[str]:
    path = ROOT / "predictions" / "picks.csv"
    if not path.exists():
        return []
    new = pd.read_csv(path, dtype=str).fillna("")
    old_text = git_show("predictions/picks.csv", ref)
    if old_text is None:
        return ["picks: duplicate pick_id in predictions/picks.csv"] if new["pick_id"].duplicated().any() else []
    old = pd.read_csv(io.StringIO(old_text), dtype=str).fillna("")
    return picks_problems(old, new)


def check_site() -> list[str]:
    probs = []
    idx = ROOT / "docs" / "index.html"
    if not idx.exists():
        return ["site: docs/index.html is missing"]
    html = idx.read_text()
    if not re.search(r"Data through \d{4}-\d{2}-\d{2}", html):
        probs.append("site: docs/index.html does not state the data date")
    for href in set(re.findall(r"href=['\"]([^'\"#?]+\.(?:html|png|svg|csv|md))['\"]", html)):
        if href.startswith("http"):
            continue
        if not (ROOT / "docs" / href).exists() and not (ROOT / href).exists():
            probs.append(f"site: docs/index.html links to {href}, which does not exist")
    return probs


def run_checks(ref: str = "HEAD") -> list[str]:
    probs = []
    probs += check_data(ref)
    probs += check_boards()
    for extra in sorted((OUT / "boards").glob("v*/composite_rankings_full.csv")):
        probs += check_boards(extra, label=f"boards {extra.parent.name}")
    probs += check_history(ref)
    probs += check_picks(ref)
    probs += check_site()
    return probs


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Sanity checks before the weekly commit")
    ap.add_argument("--ref", default="HEAD", help="git ref to compare the append-only files with")
    a = ap.parse_args(argv)
    probs = run_checks(a.ref)
    if probs:
        print(f"{len(probs)} problem(s):")
        for p in probs:
            print(" -", p)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
