"""
ingest.py - Load raw UFCStats CSVs (Greco1899/scrape_ufc_stats format) and
produce three clean tables:

    data/processed/bouts.csv        one row per bout (fighter A / fighter B, winner, method, date, division)
    data/processed/round_stats.csv  one row per fighter per round (numeric)
    data/processed/fighters.csv     tale of the tape (height, reach, stance, DOB)

Why this layer exists: every downstream module (Elo, features, rankings,
card quality) reads these three files and nothing else, so a change in the
scraper only ever touches this file.

Same-name fighters (data finding D8): UFCStats gives a few distinct fighters
(different fighter-details URLs) one display name, and the bout files carry only
the name. config/fighter_disambiguation.yaml assigns every bout of a shared name
to one fighter (explicit bout URLs first, then the bout's division) and gives each
fighter but one a suffixed display name, written here into all three tables. A
shared name the file does not list, or a bout no entry claims, stops ingest with
an error, so a data refresh can never silently merge two careers again.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
PROC = Path(__file__).resolve().parents[2] / "data" / "processed"
CONFIG = Path(__file__).resolve().parents[2] / "config"
DISAMBIGUATION_PATH = CONFIG / "fighter_disambiguation.yaml"

DIVISIONS = [
    "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight", "Women's Featherweight",
    "Flyweight", "Bantamweight", "Featherweight", "Lightweight", "Welterweight",
    "Middleweight", "Light Heavyweight", "Heavyweight",
]
# Order matters: check women's first so "Women's Flyweight" is not read as "Flyweight".
_DIV_PATTERNS = [(d, re.compile(re.escape(d), re.I)) for d in DIVISIONS]
# Every label parse_division can emit; the disambiguation file may only name these.
DIVISION_LABELS = DIVISIONS + ["Catch Weight", "Open Weight", "Unknown"]

# Known naming mismatches between the results file and the events file. The round stats carry the
# results file's spelling; bout_stats.py applies the same map before joining them to bouts.csv.
EVENT_ALIASES = {
    "UFC Fight Night: Grasso vs. Shevchenko 2": "Noche UFC: Grasso vs. Shevchenko 2",
    "UFC Fight Night: Lopes vs. Silva": "Noche UFC: Lopes vs. Silva",
}


class DisambiguationError(ValueError):
    """config/fighter_disambiguation.yaml does not settle a shared fighter name."""


def parse_division(weightclass: str) -> str:
    wc = (weightclass or "").strip()
    for name, pat in _DIV_PATTERNS:
        if pat.search(wc):
            return name
    if "catch" in wc.lower():
        return "Catch Weight"
    if "open" in wc.lower():
        return "Open Weight"
    return "Unknown"


def parse_method(method: str) -> str:
    m = (method or "").strip().lower()
    if m.startswith("ko/tko") or "doctor" in m:
        return "KO/TKO"
    if m.startswith("submission"):
        return "SUB"
    if m.startswith("decision - unanimous"):
        return "U-DEC"
    if m.startswith("decision - split"):
        return "S-DEC"
    if m.startswith("decision - majority"):
        return "M-DEC"
    if m.startswith("dq"):
        return "DQ"
    if "overturned" in m or "could not continue" in m:
        return "NC"
    return "OTHER"


def _of(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Split '29 of 73' into (29, 73)."""
    parts = series.astype(str).str.extract(r"(\d+)\s+of\s+(\d+)")
    return (pd.to_numeric(parts[0], errors="coerce").fillna(0).astype(int),
            pd.to_numeric(parts[1], errors="coerce").fillna(0).astype(int))


def _mmss(series: pd.Series) -> pd.Series:
    """'4:32' -> 272 seconds. '--' -> 0."""
    parts = series.astype(str).str.extract(r"(\d+):(\d+)")
    return (pd.to_numeric(parts[0], errors="coerce").fillna(0) * 60
            + pd.to_numeric(parts[1], errors="coerce").fillna(0)).astype(int)


def _inches(series: pd.Series) -> pd.Series:
    """5' 11" -> 71 ; 72" -> 72 ; '--' -> NaN"""
    s = series.astype(str)
    ft = s.str.extract(r"(\d+)'\s*(\d+)")
    inches_only = s.str.extract(r"^(\d+)\"")[0]
    out = pd.to_numeric(ft[0], errors="coerce") * 12 + pd.to_numeric(ft[1], errors="coerce")
    out = out.fillna(pd.to_numeric(inches_only, errors="coerce"))
    return out


def build_bouts() -> pd.DataFrame:
    res = pd.read_csv(RAW / "ufc_fight_results.csv")
    res.columns = [c.strip() for c in res.columns]
    for c in ["EVENT", "BOUT", "OUTCOME", "WEIGHTCLASS", "METHOD"]:
        res[c] = res[c].astype(str).str.strip()

    ev = pd.read_csv(RAW / "ufc_event_details.csv")
    ev.columns = [c.strip() for c in ev.columns]
    ev["EVENT"] = ev["EVENT"].astype(str).str.strip()
    ev["date"] = pd.to_datetime(ev["DATE"], format="%B %d, %Y", errors="coerce")
    ev = ev.rename(columns={"LOCATION": "location", "URL": "event_url"})[["EVENT", "date", "location", "event_url"]]

    res["EVENT"] = res["EVENT"].replace(EVENT_ALIASES)
    # the scraper lists two Noche UFC cards under both of their names; keep one copy of each bout
    res = res.drop_duplicates(subset="URL", keep="first")
    df = res.merge(ev, on="EVENT", how="left")
    # Road to UFC 4.6 (Shanghai, Aug 2025 finals) is absent from the events file.
    mask = df["date"].isna() & df["EVENT"].str.contains("Road to UFC 4", case=False)
    df.loc[mask, "date"] = pd.Timestamp("2025-08-23")
    df.loc[mask, "location"] = "Shanghai, China"
    names = df["BOUT"].str.split(r"\s+vs\.\s+", n=1, expand=True, regex=True)
    df["fighter_a"] = names[0].str.strip()
    df["fighter_b"] = names[1].str.strip()

    # OUTCOME is from fighter_a's perspective: W/L means A won.
    out = df["OUTCOME"].str.upper()
    df["result_a"] = np.select(
        [out.eq("W/L"), out.eq("L/W"), out.eq("D/D")],
        [1.0, 0.0, 0.5], default=np.nan)          # NaN = no contest
    df["division"] = df["WEIGHTCLASS"].map(parse_division)
    df["title_fight"] = df["WEIGHTCLASS"].str.contains("Title", case=False, na=False) & \
        df["WEIGHTCLASS"].str.contains("UFC", case=False, na=False)
    df["interim"] = df["WEIGHTCLASS"].str.contains("Interim", case=False, na=False)
    df["method"] = df["METHOD"].map(parse_method)
    df["round"] = pd.to_numeric(df["ROUND"], errors="coerce")
    df["time_sec"] = _mmss(df["TIME"])
    df["sched_rounds"] = pd.to_numeric(
        df["TIME FORMAT"].astype(str).str.extract(r"^(\d+)")[0], errors="coerce")
    df["fight_seconds"] = (df["round"].fillna(1) - 1) * 300 + df["time_sec"]
    df["finish"] = df["method"].isin(["KO/TKO", "SUB"])
    df["bout_url"] = df["URL"]
    df["event"] = df["EVENT"]
    df["is_numbered"] = df["event"].str.match(r"^UFC \d+")

    cols = ["event", "date", "location", "is_numbered", "division", "title_fight", "interim",
            "fighter_a", "fighter_b", "result_a", "method", "round", "time_sec",
            "sched_rounds", "fight_seconds", "finish", "bout_url", "event_url"]
    df = df[cols].sort_values(["date", "event", "bout_url"]).reset_index(drop=True)
    df["bout_id"] = np.arange(len(df))
    return df


def build_round_stats() -> pd.DataFrame:
    s = pd.read_csv(RAW / "ufc_fight_stats.csv")
    s.columns = [c.strip() for c in s.columns]
    for c in ["EVENT", "BOUT", "FIGHTER"]:
        s[c] = s[c].astype(str).str.strip()
    out = pd.DataFrame({
        "event": s["EVENT"], "bout": s["BOUT"], "fighter": s["FIGHTER"],
        "round": pd.to_numeric(s["ROUND"].str.extract(r"(\d+)")[0], errors="coerce"),
        "kd": pd.to_numeric(s["KD"], errors="coerce").fillna(0).astype(int),
        "sub_att": pd.to_numeric(s["SUB.ATT"], errors="coerce").fillna(0).astype(int),
        "rev": pd.to_numeric(s["REV."], errors="coerce").fillna(0).astype(int),
        "ctrl_sec": _mmss(s["CTRL"]),
    })
    out["sig_landed"], out["sig_att"] = _of(s["SIG.STR."])
    out["tot_landed"], out["tot_att"] = _of(s["TOTAL STR."])
    out["td_landed"], out["td_att"] = _of(s["TD"])
    out["head_landed"], _ = _of(s["HEAD"])
    out["body_landed"], _ = _of(s["BODY"])
    out["leg_landed"], _ = _of(s["LEG"])
    out["dist_landed"], _ = _of(s["DISTANCE"])
    out["clinch_landed"], _ = _of(s["CLINCH"])
    out["ground_landed"], _ = _of(s["GROUND"])
    return out


def read_fighter_files() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The two raw fighter files (tale of the tape, name details) with stripped column names."""
    t = pd.read_csv(RAW / "ufc_fighter_tott.csv")
    t.columns = [c.strip() for c in t.columns]
    d = pd.read_csv(RAW / "ufc_fighter_details.csv")
    d.columns = [c.strip() for c in d.columns]
    return t, d


def build_fighters(tott: pd.DataFrame | None = None, names_by_url: dict[str, str] | None = None) -> pd.DataFrame:
    """Tale of the tape, one row per display name. `names_by_url` (fighter URL -> display name, from
    the disambiguation file) renames a same-name fighter's row before duplicates are dropped."""
    t = read_fighter_files()[0] if tott is None else tott
    f = pd.DataFrame({
        "fighter": t["FIGHTER"].astype(str).str.strip(),
        "height_in": _inches(t["HEIGHT"]),
        "reach_in": pd.to_numeric(t["REACH"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"),
        "weight_lb": pd.to_numeric(t["WEIGHT"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"),
        "stance": t["STANCE"].fillna("").astype(str).str.strip().replace("", np.nan),
        "dob": pd.to_datetime(t["DOB"], format="%b %d, %Y", errors="coerce"),
        "fighter_url": t["URL"],
    })
    if names_by_url:
        idx = f.index[f["fighter_url"].isin(names_by_url)]
        f.loc[idx, "fighter"] = f.loc[idx, "fighter_url"].map(names_by_url).to_numpy()
    return f.drop_duplicates("fighter", keep="first").reset_index(drop=True)


# ---------- same-name fighters ----------

def load_disambiguation(path: Path = DISAMBIGUATION_PATH) -> dict[str, list[dict]]:
    """Shared display name -> entries, each {url, name, divisions, bout_urls}, checked for shape: at
    least two entries per name, exactly one of them keeping the plain name and the rest suffixed as
    'Name (suffix)', distinct URLs and names, known division labels, no division or bout URL claimed
    twice. A missing or empty file means nothing is settled."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise DisambiguationError(f"{path.name} must map each shared name to a list of entries")
    out: dict[str, list[dict]] = {}
    for raw_name, entries in data.items():
        shared = str(raw_name).strip()
        if not isinstance(entries, list) or len(entries) < 2:
            raise DisambiguationError(f"{path.name}: {shared!r} needs a list of at least two entries, one per fighter URL")
        clean: list[dict] = []
        for e in entries:
            if not isinstance(e, dict) or not e.get("url") or not e.get("name"):
                raise DisambiguationError(f"{path.name}: every entry under {shared!r} needs 'url' and 'name'")
            divisions = [str(d).strip() for d in (e.get("divisions") or [])]
            bad = sorted(set(divisions) - set(DIVISION_LABELS))
            if bad:
                raise DisambiguationError(f"{path.name}: {shared!r} lists unknown divisions {bad}; use {DIVISION_LABELS}")
            clean.append({"url": str(e["url"]).strip(), "name": str(e["name"]).strip(), "divisions": divisions,
                          "bout_urls": [str(u).strip() for u in (e.get("bout_urls") or [])]})
        names = [e["name"] for e in clean]
        if len(set(names)) != len(names):
            raise DisambiguationError(f"{path.name}: {shared!r} gives two entries the same display name")
        if sum(n == shared for n in names) != 1:
            raise DisambiguationError(f"{path.name}: exactly one entry under {shared!r} must keep the plain name {shared!r}")
        for n in names:
            if n != shared and not (n.startswith(shared + " (") and n.endswith(")") and len(n) > len(shared) + 3):
                raise DisambiguationError(f"{path.name}: {n!r} must be {shared!r} followed by a suffix in parentheses")
        urls = [e["url"] for e in clean]
        if len(set(urls)) != len(urls):
            raise DisambiguationError(f"{path.name}: {shared!r} lists a fighter URL twice")
        for key in ("divisions", "bout_urls"):
            claimed: dict[str, str] = {}
            for e in clean:
                for v in e[key]:
                    if v in claimed and claimed[v] != e["name"]:
                        raise DisambiguationError(f"{path.name}: {shared!r} claims {v!r} for both {claimed[v]!r} and {e['name']!r}")
                    claimed[v] = e["name"]
        out[shared] = clean
    return out


def shared_display_names(tott: pd.DataFrame, details: pd.DataFrame | None = None) -> dict[str, set[str]]:
    """Display names that a fighter file gives to more than one fighter URL, with those URLs. Both
    files are checked on their own (ufc_fighter_tott.csv names the fighter page, ufc_fighter_details.csv
    carries first and last name), so a name shared in either one is caught."""
    frames = [pd.DataFrame({"name": tott["FIGHTER"].astype(str).str.strip(), "url": tott["URL"]})]
    if details is not None:
        full = (details["FIRST"].fillna("").astype(str).str.strip() + " "
                + details["LAST"].fillna("").astype(str).str.strip()).str.strip()
        frames.append(pd.DataFrame({"name": full, "url": details["URL"]}))
    out: dict[str, set[str]] = {}
    for f in frames:
        f = f.dropna().drop_duplicates()
        f = f[f["name"] != ""]
        counts = f.groupby("name")["url"].nunique()
        for name in counts[counts > 1].index:
            out.setdefault(str(name), set()).update(f.loc[f["name"] == name, "url"])
    return out


def check_disambiguation(config: dict[str, list[dict]], shared: dict[str, set[str]], taken: set[str]) -> None:
    """Every shared name has entries for exactly its fighter URLs, no entry is stale, and no suffixed
    display name (`taken`: every name in the fighter and bout files) already belongs to someone."""
    missing = sorted(set(shared) - set(config))
    if missing:
        detail = "; ".join(f"{n} ({', '.join(sorted(u.rsplit('/', 1)[-1] for u in shared[n]))})" for n in missing)
        raise DisambiguationError(
            f"shared display names with no entry in {DISAMBIGUATION_PATH.name}: {detail}. "
            "Add one entry per fighter URL (name, divisions or bout_urls) so their bouts are not merged.")
    stale = sorted(set(config) - set(shared))
    if stale:
        raise DisambiguationError(
            f"{DISAMBIGUATION_PATH.name} lists names the fighter files no longer share: {', '.join(stale)}. "
            "Remove the entries or correct the name.")
    for name, entries in config.items():
        urls = {e["url"] for e in entries}
        if urls != shared[name]:
            raise DisambiguationError(
                f"{DISAMBIGUATION_PATH.name}: {name!r} fighter URLs differ from the fighter files; "
                f"only in config: {sorted(urls - shared[name])}, only in the files: {sorted(shared[name] - urls)}")
        for e in entries:
            if e["name"] != name and e["name"] in taken:
                raise DisambiguationError(f"{DISAMBIGUATION_PATH.name}: display name {e['name']!r} already belongs to another fighter")


def assign_shared_bouts(bouts: pd.DataFrame, config: dict[str, list[dict]]) -> pd.DataFrame:
    """One row per (bout_url, side) that carries a shared name, with the display name that side takes:
    an entry's explicit bout_urls win, then the bout's division. A bout no entry claims, an explicit
    bout URL that is not one of the name's bouts, or a bout listing the name on both sides is an error."""
    rows = []
    for shared, entries in config.items():
        by_url = {u: e["name"] for e in entries for u in e["bout_urls"]}
        by_div = {d: e["name"] for e in entries for d in e["divisions"]}
        is_a, is_b = bouts["fighter_a"] == shared, bouts["fighter_b"] == shared
        both = bouts.loc[is_a & is_b, "bout_url"].tolist()
        if both:
            raise DisambiguationError(f"{shared}: {both} list the name on both sides; the bout files cannot tell the two apart")
        unknown = sorted(set(by_url) - set(bouts.loc[is_a | is_b, "bout_url"]))
        if unknown:
            raise DisambiguationError(f"{shared}: bout_urls {unknown} are not bouts of this name in the results file")
        for side, mask in (("fighter_a", is_a), ("fighter_b", is_b)):
            sub = bouts.loc[mask, ["bout_url", "division", "event", "date", "fighter_a", "fighter_b"]]
            new = [by_url.get(u) or by_div.get(d) for u, d in zip(sub["bout_url"], sub["division"])]
            lost = [r for r, n in zip(sub.itertuples(index=False), new) if n is None]
            if lost:
                lines = [f"{str(r.date)[:10]} {r.event}: {r.fighter_a} vs. {r.fighter_b} ({r.division}) {r.bout_url}" for r in lost]
                raise DisambiguationError(
                    f"{shared}: {len(lost)} bout(s) claimed by no entry in {DISAMBIGUATION_PATH.name}; add the division to "
                    "the right entry's divisions or the bout URL to its bout_urls:\n  " + "\n  ".join(lines))
            rows.append(pd.DataFrame({"bout_url": sub["bout_url"].to_numpy(), "side": side, "old": shared, "new": new}))
    if not rows:
        return pd.DataFrame(columns=["bout_url", "side", "old", "new"])
    return pd.concat(rows, ignore_index=True)


def rename_shared(bouts: pd.DataFrame, rounds: pd.DataFrame, assigned: pd.DataFrame,
                  shared_names: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Write the assigned display names into bouts (fighter_a / fighter_b) and into the round stats
    (fighter and the 'A vs. B' bout label bout_stats.py joins on). Every other row is left untouched.
    A round-stat row of a shared name whose bout is not in `bouts` is an error."""
    bouts, rounds = bouts.copy(), rounds.copy()
    by_side: dict[str, dict[str, str]] = {"fighter_a": {}, "fighter_b": {}}
    for r in assigned.itertuples(index=False):
        by_side[r.side][r.bout_url] = r.new
    hit = bouts["bout_url"].isin(set(assigned["bout_url"]))
    old = bouts.loc[hit, ["event", "fighter_a", "fighter_b"]].copy()
    for side, names in by_side.items():
        idx = bouts.index[bouts["bout_url"].isin(names)]
        bouts.loc[idx, side] = bouts.loc[idx, "bout_url"].map(names).to_numpy()
    new = bouts.loc[hit, ["fighter_a", "fighter_b"]]
    label = {(ev, f"{oa} vs. {ob}"): (oa, ob, na, nb)
             for (ev, oa, ob), (na, nb) in zip(old.itertuples(index=False), new.itertuples(index=False))}

    keys = list(zip(rounds["event"].replace(EVENT_ALIASES), rounds["bout"]))
    fighters = rounds["fighter"].tolist()
    i_bout, i_fighter = rounds.columns.get_loc("bout"), rounds.columns.get_loc("fighter")
    orphans = []
    for i, key in enumerate(keys):
        if key in label:
            oa, ob, na, nb = label[key]
            rounds.iat[i, i_bout] = f"{na} vs. {nb}"
            if fighters[i] == oa:
                rounds.iat[i, i_fighter] = na
            elif fighters[i] == ob:
                rounds.iat[i, i_fighter] = nb
        elif fighters[i] in shared_names:
            orphans.append(f"{key[0]}: {key[1]}")
    if orphans:
        raise DisambiguationError(
            "round stats of a shared name belong to no bout in the results file, so they cannot be assigned: "
            + "; ".join(sorted(set(orphans))))
    return bouts, rounds


def disambiguate(bouts: pd.DataFrame, rounds: pd.DataFrame, tott: pd.DataFrame, details: pd.DataFrame | None,
                 config: dict[str, list[dict]]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str], pd.DataFrame]:
    """Settle every shared display name: validate `config` against the fighter files, assign the bouts,
    rename bouts and round stats. Returns (bouts, rounds, fighter URL -> display name, assignments)."""
    shared = shared_display_names(tott, details)
    taken = set(tott["FIGHTER"].dropna().astype(str).str.strip()) | set(bouts["fighter_a"]) | set(bouts["fighter_b"])
    if details is not None:
        taken |= set((details["FIRST"].fillna("").astype(str).str.strip() + " "
                      + details["LAST"].fillna("").astype(str).str.strip()).str.strip())
    check_disambiguation(config, shared, taken)
    assigned = assign_shared_bouts(bouts, config)
    bouts, rounds = rename_shared(bouts, rounds, assigned, set(config))
    names_by_url = {e["url"]: e["name"] for entries in config.values() for e in entries}
    return bouts, rounds, names_by_url, assigned


def main() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    bouts = build_bouts()
    rounds = build_round_stats()
    tott, details = read_fighter_files()
    config = load_disambiguation()
    bouts, rounds, names_by_url, assigned = disambiguate(bouts, rounds, tott, details, config)
    fighters = build_fighters(tott, names_by_url)
    bouts.to_csv(PROC / "bouts.csv", index=False)
    rounds.to_csv(PROC / "round_stats.csv", index=False)
    fighters.to_csv(PROC / "fighters.csv", index=False)
    print(f"bouts: {len(bouts):,}  ({bouts['date'].min().date()} to {bouts['date'].max().date()})")
    print(f"  no-contests dropped later: {bouts['result_a'].isna().sum()}, draws: {(bouts['result_a']==0.5).sum()}")
    print(f"  unmatched event dates: {bouts['date'].isna().sum()}")
    print(f"round_stats: {len(rounds):,} rows;  fighters: {len(fighters):,}")
    renamed = assigned[assigned["old"] != assigned["new"]]
    detail = ", ".join(f"{n} x{c}" for n, c in renamed["new"].value_counts().items())
    print(f"shared names: {len(config)} settled over {len(names_by_url)} fighter pages; "
          f"{len(assigned)} bouts assigned, {len(renamed)} renamed" + (f" ({detail})" if detail else ""))
    print(bouts["division"].value_counts().to_string())


if __name__ == "__main__":
    main()
