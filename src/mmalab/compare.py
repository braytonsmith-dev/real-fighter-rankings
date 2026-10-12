"""
compare.py - Compare MMA Lab boards against public ranking systems.

Inputs (data/external/*.csv, header: source,division,rank,fighter,is_champion,is_interim,as_of,url[,promotion]):
  ufc_media.csv    UFC media panel (champion + 1-15)
  ufc_meta.csv     Meta UFC Rankings (champion + 1-15)
  sherdog.csv      Sherdog, all promotions, top 10, no champion slot
  fightmatrix.csv  Fight Matrix, all promotions, top 15, no champion slot
  espn.csv         ESPN panel, all promotions, top 10 (June 2026 edition)

Apples to apples: every board is reduced to "UFC contender position" within
the division: drop non-UFC fighters and the reigning UFC champion, then
renumber 1..n in the order given. MMA Lab uses its contender rank the same way.

Outputs:
  outputs/compare_long.csv        one row per (source, division, fighter) with both positions
  outputs/compare_consensus.csv   per fighter: MMA Lab position vs median of external boards
  outputs/compare_flags.csv       vast deviations with a plain-language reason code
  outputs/compare_agreement.csv   Spearman agreement by source and division (shared fighters)
  outputs/compare_report.md       readable summary
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.rankings import RANKED_DIVISIONS, champions
from mmalab.elo import EloParams, run_elo

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "data" / "external"
OUT = ROOT / "outputs"
PROC = ROOT / "data" / "processed"

SOURCES = {
    "ufc_media.csv": "UFC media",
    "ufc_meta.csv": "Meta",
    "sherdog.csv": "Sherdog",
    "fightmatrix.csv": "Fight Matrix",
    "espn.csv": "ESPN (Jun)",
}

# spelling differences between boards and UFCStats (normalized form -> UFCStats normalized form)
ALIASES = {
    "yadong song": "song yadong", "weili zhang": "zhang weili", "xiaonan yan": "yan xiaonan",
    "cong wang": "wang cong", "benoit st denis": "benoit saint denis", "ian garry": "ian machado garry",
    "lupita godinez": "loopy godinez", "khalil rountree": "khalil rountree jr",
    "mizuki": "mizuki inoue", "bia mesquita": "beatriz mesquita", "patricio pitbull": "patricio freire",
    "loneer kavanagh": "loneer kavanagh", "waldo cortesacosta": "waldo cortes acosta",
    "jiri prochazka": "jiri prochazka", "abusupiyan magomedov": "abus magomedov",
    "ramazonbek temirov": "ramazan temirov", "phil de fries": "philip de fries",
}

DEVIATION = 5          # positions apart on a 15-deep board counts as a vast deviation


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = s.replace("-", " ")
    s = re.sub(r"[^a-z ]", "", s)
    s = " ".join(s.split())
    return ALIASES.get(s, s)


def load_external() -> pd.DataFrame:
    frames = []
    for fname, label in SOURCES.items():
        p = EXT / fname
        if not p.exists():
            continue
        d = pd.read_csv(p)
        if "as_of" in d.columns:            # a file may hold several dated snapshots; keep the latest per division
            d = d[d["as_of"] == d.groupby("division")["as_of"].transform("max")]
        d["source"] = label
        if "promotion" not in d.columns:
            d["promotion"] = "UFC"
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["promotion"] = df["promotion"].fillna("")
    df["key"] = df["fighter"].map(norm)
    return df


def lab_board() -> pd.DataFrame:
    b = pd.read_csv(OUT / "composite_rankings_full.csv")
    b["key"] = b["fighter"].map(norm)
    return b


def resolve_names(ext: pd.DataFrame, known: set[str]) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Map unmatched keys to the closest UFCStats name when the match is unambiguous."""
    fixes = []
    for k in sorted(set(ext["key"]) - known):
        cand = difflib.get_close_matches(k, list(known), n=1, cutoff=0.88)
        if not cand:
            continue
        # every name part must match closely, so Usman != Umar Nurmagomedov
        a, b = k.split(), cand[0].split()
        if len(a) != len(b) or any(difflib.SequenceMatcher(None, x, y).ratio() < 0.85 for x, y in zip(a, b)):
            continue
        fixes.append((k, cand[0]))
    m = dict(fixes)
    ext["key"] = ext["key"].map(lambda k: m.get(k, k))
    return ext, fixes


def contender_positions(ext: pd.DataFrame, ufc_names: set[str], champs_key: dict[str, str],
                        interim_key: dict[str, str]) -> pd.DataFrame:
    rows = []
    for (src, div), g in ext.groupby(["source", "division"], sort=False):
        g = g.sort_values("rank", kind="stable")
        champ = champs_key.get(div)
        pos = 0
        for r in g.itertuples():
            # a stated non-UFC promotion wins over old UFC history (e.g. de Fries, Ngannou)
            non_ufc = (r.promotion not in ("", "UFC")) or (r.key not in ufc_names)
            is_title = (r.key == champ) or (r.key == interim_key.get(div))
            if non_ufc or is_title or r.rank == 0:
                rows.append({"source": src, "division": div, "key": r.key, "fighter": r.fighter,
                             "raw_rank": r.rank, "position": np.nan,
                             "excluded": "non-UFC" if non_ufc else "title holder"})
                continue
            pos += 1
            rows.append({"source": src, "division": div, "key": r.key, "fighter": r.fighter,
                         "raw_rank": r.rank, "position": pos, "excluded": "", "as_of": r.as_of})
    return pd.DataFrame(rows)


def reason(row: pd.Series, lab: pd.DataFrame, bouts_recent: pd.DataFrame, as_of: pd.Timestamp) -> str:
    """Plain-language reason for a big gap, from the fighter's own data."""
    k = row["key"]
    mine = lab[lab["key"] == k]
    if mine.empty:
        last = bouts_recent[(bouts_recent["ka"] == k) | (bouts_recent["kb"] == k)]
        if last.empty:
            return "Not in UFC data (no UFC bout on record)"
        d = last["date"].max()
        return f"Inactive: last UFC bout {d.date()} ({(as_of - d).days} days), outside the 540-day window"
    m = mine.iloc[0]
    if m["division"] != row["division"]:
        return f"Model places this fighter in {m['division']} (division of most recent bout)"
    notes = []
    if m.get("ufc_bouts", 99) <= 3:
        notes.append(f"only {int(m['ufc_bouts'])} UFC bouts")
    if m.get("top15_wins", 1) == 0:
        notes.append("no quality wins")
    if m.get("days_since", 0) > 300:
        notes.append(f"{int(m['days_since'])} days since last bout")
    rec = str(m.get("last5", m.get("record_3y", "0-0")))
    try:
        w, l = (int(x) for x in rec.split("-"))
        if l > w:
            notes.append(f"last five {rec}")
    except ValueError:
        pass
    if not notes:
        notes.append(f"rating {m['rating']:.0f}, last five {rec}")
    return "; ".join(notes)


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config" / "weights.yaml").read_text())
    lab = lab_board()
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    as_of = bouts["date"].max()
    rated, _ = run_elo(bouts, EloParams(**cfg["elo"]))
    champs = champions(rated, as_of)
    champs_key = {d: norm(n) for d, n in champs.items()}
    interim_key = {"Heavyweight": norm("Ciryl Gane")}

    ufc_names = set(pd.concat([bouts["fighter_a"], bouts["fighter_b"]]).map(norm))
    ext = load_external()
    ext, fixes = resolve_names(ext, ufc_names)
    pos = contender_positions(ext, ufc_names, champs_key, interim_key)

    # MMA Lab contender position by division (the champion is rank 0, contenders 1..n)
    # interim champions sit outside the contender numbering, as on the official boards
    lab = lab[~lab["key"].isin(set(interim_key.values()))].copy()
    cont = lab["rank"] >= 1
    lab.loc[cont, "rank"] = lab[cont].groupby("division")["rank"].rank(method="first").astype(int)
    labpos = lab[["key", "fighter", "division", "rank", "rank_p10", "rank_p90", "score"]].rename(
        columns={"rank": "lab_position", "division": "lab_division", "fighter": "lab_fighter"})
    long = pos.merge(labpos, on="key", how="left")
    long.loc[long["lab_position"] == 0, "lab_position"] = np.nan    # model champion row
    # interim champions are title holders on every board; treat the model the same way
    for d, k in interim_key.items():
        long.loc[(long["key"] == k), "lab_position"] = np.nan
    same_div = long["lab_division"] == long["division"]
    long["lab_position_same_div"] = long["lab_position"].where(same_div)
    long["gap"] = long["lab_position_same_div"] - long["position"]
    OUT.mkdir(exist_ok=True)
    long.to_csv(OUT / "compare_long.csv", index=False)

    # consensus across external boards
    ranked = long[long["position"].notna()]
    cons = ranked.groupby(["division", "key"]).agg(
        fighter=("fighter", "first"), boards=("source", "nunique"),
        sources=("source", lambda s: ", ".join(sorted(s))),
        median_position=("position", "median"), best=("position", "min"), worst=("position", "max"),
        lab_position=("lab_position_same_div", "first"), lab_division=("lab_division", "first")).reset_index()
    # fighters our board has top 10 that no external board ranks
    lab_top = lab[(lab["rank"] >= 1) & (lab["rank"] <= 10) & ~lab["key"].isin(set(interim_key.values()))]
    ranked_keys = set(zip(ranked["division"], ranked["key"]))
    lab_only = lab_top[[ (d, k) not in ranked_keys for d, k in zip(lab_top["division"], lab_top["key"])]]
    lab_only_rows = pd.DataFrame({
        "division": lab_only["division"], "key": lab_only["key"], "fighter": lab_only["fighter"],
        "boards": 0, "sources": "", "median_position": np.nan, "best": np.nan, "worst": np.nan,
        "lab_position": lab_only["rank"], "lab_division": lab_only["division"]})
    cons = pd.concat([cons, lab_only_rows], ignore_index=True)
    cons["gap_vs_median"] = cons["lab_position"] - cons["median_position"]
    cons.to_csv(OUT / "compare_consensus.csv", index=False)

    # flags
    bouts_recent = bouts.assign(ka=bouts["fighter_a"].map(norm), kb=bouts["fighter_b"].map(norm))
    flags = []
    for r in cons.itertuples():
        typ = None
        if r.boards >= 2 and pd.isna(r.lab_position) and r.median_position <= 10:
            typ = "Consensus ranked, ours outside top 15"
            if not lab[(lab["key"] == r.key)].empty and lab.loc[lab["key"] == r.key, "division"].iloc[0] == r.division:
                lp = int(lab.loc[lab["key"] == r.key, "rank"].iloc[0])
                typ = f"Consensus ranked, our board has #{lp}"
        elif r.boards >= 2 and not pd.isna(r.lab_position) and abs(r.gap_vs_median) >= DEVIATION:
            typ = "Ours higher" if r.gap_vs_median < 0 else "Ours lower"
        elif r.boards == 0:
            typ = "Our top 10, unranked on every board"
        if typ:
            flags.append({"division": r.division, "fighter": r.fighter, "type": typ,
                          "lab_position": r.lab_position, "median_external": r.median_position,
                          "external_range": "" if pd.isna(r.best) else f"{int(r.best)}-{int(r.worst)}",
                          "boards": r.boards, "sources": r.sources, "key": r.key})
    flags = pd.DataFrame(flags)
    # attach full-board model position for "outside top 15"
    fullpos = lab.set_index("key")["rank"].to_dict()
    flags["lab_full_position"] = flags["key"].map(fullpos)
    flags["reason"] = [reason(pd.Series({"key": f.key, "division": f.division}), lab, bouts_recent, as_of)
                       for f in flags.itertuples()]
    flags["abs_gap"] = (flags["lab_full_position"].fillna(40) - flags["median_external"].fillna(0)).abs()
    flags = flags.sort_values(["type", "abs_gap"], ascending=[True, False])
    flags.drop(columns=["key"]).to_csv(OUT / "compare_flags.csv", index=False)

    # agreement: Spearman on shared fighters, by source and division
    agree = []
    for (src, div), g in ranked.groupby(["source", "division"]):
        s = g.dropna(subset=["lab_position_same_div"])
        if len(s) >= 5:
            rho = s["position"].rank().corr(s["lab_position_same_div"].rank(), method="pearson")
        else:
            rho = np.nan
        agree.append({"source": src, "division": div, "board_size": len(g), "shared_in_lab_top15":
                      int((s["lab_position_same_div"] <= 15).sum()), "spearman": rho})
    agree = pd.DataFrame(agree)
    agree.to_csv(OUT / "compare_agreement.csv", index=False)

    # external boards vs each other, as a yardstick for "normal" disagreement
    pairs = []
    srcs = ranked["source"].unique().tolist() + ["Our board"]
    lab_as_src = labpos[(labpos["lab_position"] >= 1) & (labpos["lab_position"] <= 15)].rename(
        columns={"lab_division": "division", "lab_position": "position"})
    lab_as_src["source"] = "Our board"
    allpos = pd.concat([ranked[["source", "division", "key", "position"]],
                        lab_as_src[["source", "division", "key", "position"]]])
    for i, a in enumerate(srcs):
        for b in srcs[i + 1:]:
            m = allpos[allpos["source"] == a].merge(allpos[allpos["source"] == b], on=["division", "key"])
            top_a = allpos[(allpos["source"] == a) & (allpos["position"] <= 10)]
            top_b = allpos[(allpos["source"] == b) & (allpos["position"] <= 10)]
            ov = top_a.merge(top_b, on=["division", "key"])
            pairs.append({"a": a, "b": b, "shared": len(m),
                          "mean_abs_gap": round((m["position_x"] - m["position_y"]).abs().mean(), 2),
                          "top10_overlap_pct": round(len(ov) / max(len(top_a), 1), 3)})
    pairs = pd.DataFrame(pairs)
    pairs.to_csv(OUT / "compare_pairwise.csv", index=False)

    # report
    lines = [f"# Our board vs public boards (model data through {as_of.date()})", ""]
    lines.append("Name fixes applied by fuzzy match: " + (", ".join(f"{a} -> {b}" for a, b in fixes) or "none"))
    lines.append("")
    lines.append("## Pairwise agreement (UFC contenders only, champions removed)")
    lines.append(pairs.to_markdown(index=False))
    lines.append("")
    lines.append(f"## Vast deviations ({len(flags)})")
    lines.append(flags.drop(columns=["key", "abs_gap"]).to_markdown(index=False))
    (OUT / "compare_report.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
