"""
official_ranks.py - Official UFC media-panel rank of each fighter on any date (Feb 2013 on).

Source: martj42/ufc_rankings_history (every release 2013-02-04 to 2026-06-16), extended
with any later snapshots saved in data/external/ufc_media.csv. Rank 0 = champion.
Before Feb 2013, or for a division with no release yet, callers fall back to the
model's own position.

Name matching, in order: config/official_rank_aliases.yaml (ranking name -> UFCStats
name), then the normalised spelling, then a strict fuzzy match. Blank fighter rows
(vacant titles) are dropped. Any ranking name still unmatched must be listed in
config/official_rank_unmatched_ok.yaml (fighters with no UFCStats bouts); otherwise
the constructor raises ValueError, so a data refresh cannot silently turn a ranked
fighter into an unranked one.
"""
from __future__ import annotations

import bisect
import difflib
from pathlib import Path

import pandas as pd
import yaml

from mmalab.compare import norm

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
EXT = ROOT / "data" / "external"
PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"
ALIASES_PATH = CONFIG / "official_rank_aliases.yaml"
UNMATCHED_OK_PATH = CONFIG / "official_rank_unmatched_ok.yaml"

DIVS = {"Flyweight", "Bantamweight", "Featherweight", "Lightweight", "Welterweight", "Middleweight",
        "Light Heavyweight", "Heavyweight", "Women's Strawweight", "Women's Flyweight",
        "Women's Bantamweight", "Women's Featherweight"}


def load_aliases(path: Path = ALIASES_PATH) -> dict[str, str]:
    """Ranking-history name -> UFCStats name. Empty when the file is missing or blank."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a mapping of ranking name -> UFCStats name")
    return {str(k).strip(): str(v).strip() for k, v in data.items()}


def load_unmatched_ok(path: Path = UNMATCHED_OK_PATH) -> set[str]:
    """Ranking-history names allowed to stay unmatched (no UFCStats bouts). Accepts a
    mapping of name -> reason or a plain list of names."""
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text()) or {}
    items = data.keys() if isinstance(data, dict) else data
    return {str(x).strip() for x in items}


def load_releases() -> pd.DataFrame:
    """Every ranking release row (date, weightclass, fighter, rank) for the ranked divisions,
    with blank fighter rows (vacant titles) removed."""
    r = pd.read_csv(RAW / "ufc_rankings_history.csv")
    r = r[r["weightclass"].isin(DIVS)].copy()
    r["date"] = pd.to_datetime(r["date"])
    if (EXT / "ufc_media.csv").exists():
        m = pd.read_csv(EXT / "ufc_media.csv")
        m = pd.DataFrame({"date": pd.to_datetime(m["as_of"]), "weightclass": m["division"],
                          "fighter": m["fighter"], "rank": m["rank"]})
        r = pd.concat([r, m[m["date"] > r["date"].max()]], ignore_index=True)
    r = r.dropna(subset=["fighter"])
    r["fighter"] = r["fighter"].astype(str).str.strip()
    return r[r["fighter"] != ""].reset_index(drop=True)


def _ufc_name_universe() -> set[str]:
    """Every fighter name in data/processed/bouts.csv, or an empty set before the first ingest."""
    p = PROC / "bouts.csv"
    if not p.exists():
        return set()
    b = pd.read_csv(p, usecols=["fighter_a", "fighter_b"])
    return set(pd.concat([b["fighter_a"], b["fighter_b"]]).dropna().astype(str).str.strip())


class OfficialRanks:
    def __init__(self, ufc_names: list[str]):
        r = load_releases()
        ufc_names = [str(n).strip() for n in ufc_names if pd.notna(n) and str(n).strip()]
        name_set = set(ufc_names)
        aliases = load_aliases()
        # The guards below protect a full refresh. A caller rating a slice of bouts (tests, sensitivity runs) passes a
        # subset of the names, so the guards are checked against the whole processed roster when one exists.
        universe = _ufc_name_universe()
        strict = not universe or name_set >= universe
        bad_targets = sorted({t for t in aliases.values() if t not in name_set and t not in universe})
        if bad_targets:
            raise ValueError(
                f"{ALIASES_PATH.name}: alias targets not found among the UFCStats names: "
                + ", ".join(bad_targets) + ". Fix the target spelling or remove the entry.")
        alias_norm = {norm(k): v for k, v in aliases.items()}
        # map ranking names onto UFCStats names: alias, then normalised spelling, then strict fuzzy
        known = {norm(n): n for n in ufc_names}
        keys = list(known)
        mapping: dict[str, str] = {}
        self.unmatched: set[str] = set()
        for name in r["fighter"].unique():
            k = norm(name)
            if name in aliases:
                mapping[name] = aliases[name]
                continue
            if k in alias_norm:
                mapping[name] = alias_norm[k]
                continue
            if k in known:
                mapping[name] = known[k]
                continue
            c = difflib.get_close_matches(k, keys, n=1, cutoff=0.88)
            if c and len(c[0].split()) == len(k.split()) and all(
                    difflib.SequenceMatcher(None, x, y).ratio() >= 0.85 for x, y in zip(k.split(), c[0].split())):
                mapping[name] = known[c[0]]
            else:
                self.unmatched.add(name)
        offenders = sorted(self.unmatched - load_unmatched_ok()) if strict else []
        if offenders:
            raise ValueError(
                "official ranking names with no UFCStats match: " + ", ".join(offenders)
                + f". Add each to config/{ALIASES_PATH.name} (ranking name -> UFCStats name) or, "
                f"if the fighter has no UFCStats bouts, to config/{UNMATCHED_OK_PATH.name}.")
        n_names = r["fighter"].nunique()
        r["ufc_name"] = r["fighter"].map(mapping)
        r = r.dropna(subset=["ufc_name"])
        self.dates = sorted(r["date"].unique())
        self.first, self.last = self.dates[0], self.dates[-1]
        self.by_date: dict = {}
        for d, g in r.groupby("date"):
            self.by_date[d] = {
                "div": {(w, n): int(k) for w, n, k in zip(g["weightclass"], g["ufc_name"], g["rank"])},
                "any": g.groupby("ufc_name")["rank"].min().astype(int).to_dict(),
                "divs": set(g["weightclass"]),
            }
        self.match_rate = 1 - len(self.unmatched) / max(n_names, 1)

    def release_before(self, date) -> pd.Timestamp | None:
        i = bisect.bisect_left(self.dates, pd.Timestamp(date)) - 1
        return self.dates[i] if i >= 0 else None

    def rank(self, name: str, division: str, date) -> float | None:
        """Official rank going into a bout on `date`: 0 champion, 1-15, 99 unranked; None if no
        official board existed yet (pre-2013 or a division not yet ranked)."""
        d = self.release_before(date)
        if d is None:
            return None
        rel = self.by_date[d]
        if division in DIVS and division not in rel["divs"]:
            return None                          # division not ranked on that date
        if (division, name) in rel["div"]:
            return float(rel["div"][(division, name)])
        if name in rel["any"]:
            return float(rel["any"][name])     # ranked in another division (a mover)
        return 99.0
