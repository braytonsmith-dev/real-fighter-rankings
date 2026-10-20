"""
resume_board.py - The divisional boards (Option B): who has earned it, as of now.

score = 0.70 * rating + 0.30 * quality wins, each scaled within the division by
its interdecile range: (x - median) / (90th pct - 10th pct). Distances are kept,
so a 70-point rating gap counts more than a 5-point one (percentiles would not).

  rating         resume rating from resume.py (judges + stats, loss protection),
                 minus an inactivity penalty after 12 months unless the layoff is a
                 documented injury (config/layoffs.yaml)
  quality wins   wins over UFC fighters with 5+ UFC wins or ranked top 7 at the
                 time, weighted by age (<=3 yrs 1.0, 3-5 0.6, 5-10 0.3, 10-15 0.1);
                 each dominant loss in the last 3 years cancels one quality win
  head-to-head   if a fighter beat someone in their most recent meeting (last 3
                 years) and sits at most 3 spots below him (6 if within 12 months), he
                 moves directly above; a close win older than 12 months does not count,
                 and a fighter with a negative last five gets no lift

Display-only: last five (W-L), streak, entrenched (5+ quality wins in 15 years),
danger-adjusted durability (KO/TKO losses weighted by how dangerous the opponent was).

The five hand-kept roster files (layoffs, roster_exclusions, division_overrides, reserved,
interim_champions) hold dated entries and are read as of the board date, so a historical
rebuild applies the roster state of that date rather than today's (see *_as_of below).

Writes outputs/composite_rankings_full.csv (same columns publish.py and
compare.py read), composite_top15_by_division.csv and composite_boards.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.resume import ResumeParams, run_resume
from mmalab.rankings import RANKED_DIVISIONS, champions
from mmalab.uncertainty import board_bands

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"
CFG = ROOT / "config"


def _yaml(name: str) -> dict | list:
    """Raw contents of config/<name> ({} when the file is missing or empty)."""
    p = CFG / name
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


_LEGACY_NOTED: set[str] = set()      # files already reported as using the undated format


def _entry_date(value, name: str, field: str) -> pd.Timestamp:
    """A YAML date or 'YYYY-MM-DD' string as a Timestamp."""
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name}: '{field}' must be a date YYYY-MM-DD, got {value!r}") from e
    if pd.isna(ts):
        raise ValueError(f"{name}: '{field}' must be a date YYYY-MM-DD, got {value!r}")
    return ts


def dated_entries(name: str, as_of: pd.Timestamp, old_keys: tuple[str, str]) -> list[dict]:
    """Entries of config/<name> in effect at `as_of`.

    New format: a list of mappings, each with `since` (required), `until` (null or a date), `reason` and
    `source`. An entry applies when since <= as_of and (until is null or as_of < until).
    Old format: a plain mapping `key: value`, or a one-key item `- key: value` inside the list. Such entries
    carry no dates, are treated as always in effect, and come back as {old_keys[0]: key, old_keys[1]: value}
    with a one-line deprecation note (printed once per file per process).
    """
    raw = _yaml(name)
    as_of = pd.Timestamp(as_of)
    items: list[dict] = []
    if isinstance(raw, dict) and "since" in raw:
        raw = [raw]                                             # one dated entry written without the leading dash
    if isinstance(raw, dict):
        items = [{old_keys[0]: k, old_keys[1]: v, "_legacy": True} for k, v in raw.items()]
    elif isinstance(raw, list):
        for e in raw:
            if not isinstance(e, dict):
                raise ValueError(f"{name}: every entry must be a mapping, got {e!r}")
            if "since" in e:
                items.append(e)
            elif len(e) == 1:                                   # an old-style line added to the new list
                (k, v), = e.items()
                items.append({old_keys[0]: k, old_keys[1]: v, "_legacy": True})
            else:
                raise ValueError(f"{name}: entry {e!r} needs a 'since' date YYYY-MM-DD")
    else:
        raise ValueError(f"{name}: expected a list of dated entries, got {type(raw).__name__}")
    out, legacy = [], False
    for e in items:
        if e.get("_legacy"):
            legacy = True
            out.append(e)
            continue
        since = _entry_date(e["since"], name, "since")
        until = e.get("until")
        until = None if until is None else _entry_date(until, name, "until")
        if not e.get("source"):
            print(f"[{name}] entry {e.get(old_keys[0])!r} (since {since.date()}) has no source; every entry needs one")
        if since <= as_of and (until is None or as_of < until):
            out.append(e)
    if legacy and name not in _LEGACY_NOTED:
        _LEGACY_NOTED.add(name)
        print(f"[{name}] deprecated: undated '{old_keys[0]}: {old_keys[1]}' entries apply to every board date; "
              f"rewrite them as '- {{{old_keys[0]}: ..., since: YYYY-MM-DD, until: null, reason: ..., source: ...}}'")
    return out


def _field(e: dict, key: str, name: str) -> str:
    if key not in e or e[key] in (None, ""):
        raise ValueError(f"{name}: entry {e!r} has no '{key}'")
    return str(e[key])


def layoffs_as_of(as_of: pd.Timestamp) -> set[str]:
    """Fighters on a documented injury layoff at `as_of` (config/layoffs.yaml): no inactivity penalty."""
    return {_field(e, "fighter", "layoffs.yaml") for e in dated_entries("layoffs.yaml", as_of, ("fighter", "reason"))}


def exclusions_as_of(as_of: pd.Timestamp) -> set[str]:
    """Fighters off the UFC roster at `as_of` (config/roster_exclusions.yaml): released or retired, not back."""
    return {_field(e, "fighter", "roster_exclusions.yaml")
            for e in dated_entries("roster_exclusions.yaml", as_of, ("fighter", "reason"))}


def division_overrides_as_of(as_of: pd.Timestamp) -> dict[str, str]:
    """fighter -> division for announced moves in effect at `as_of` (config/division_overrides.yaml).
    If two entries for one fighter overlap, the later one in the file wins."""
    return {_field(e, "fighter", "division_overrides.yaml"): _field(e, "division", "division_overrides.yaml")
            for e in dated_entries("division_overrides.yaml", as_of, ("fighter", "division"))}


def reserved_as_of(as_of: pd.Timestamp) -> dict[str, str]:
    """division -> fighter holding a reserved spot at `as_of` (config/reserved.yaml)."""
    return {_field(e, "division", "reserved.yaml"): _field(e, "fighter", "reserved.yaml")
            for e in dated_entries("reserved.yaml", as_of, ("division", "fighter"))}


def interim_as_of(as_of: pd.Timestamp) -> dict[str, str]:
    """division -> interim champion at `as_of` (config/interim_champions.yaml)."""
    return {_field(e, "division", "interim_champions.yaml"): _field(e, "fighter", "interim_champions.yaml")
            for e in dated_entries("interim_champions.yaml", as_of, ("division", "fighter"))}


def fighter_ages(names, as_of: pd.Timestamp) -> pd.Series:
    """Age in years at `as_of` from data/processed/fighters.csv (NaN when the date of birth is unknown)."""
    p = PROC / "fighters.csv"
    if not p.exists():
        return pd.Series(np.nan, index=names)
    t = pd.read_csv(p, usecols=["fighter", "dob"], parse_dates=["dob"])
    dob = t.drop_duplicates("fighter").set_index("fighter")["dob"].reindex(names)
    return ((pd.Timestamp(as_of) - dob).dt.days / 365.25).rename("age")


def horizon_weight(age_years: float, horizons: dict) -> float:
    for limit in sorted(horizons):
        if age_years <= float(limit):
            return float(horizons[limit])
    return 0.0


def idr_scale(s: pd.Series) -> pd.Series:
    q10, q50, q90 = s.quantile([0.1, 0.5, 0.9])
    return (s - q50) / max(q90 - q10, 1e-9)


def last_five(out: pd.DataFrame) -> pd.DataFrame:
    rows = []
    d = out[out["result_a"].isin([0.0, 1.0])]
    long = pd.concat([
        pd.DataFrame({"fighter": d["fighter_a"], "date": d["date"], "bout_id": d["bout_id"], "w": d["result_a"] == 1.0}),
        pd.DataFrame({"fighter": d["fighter_b"], "date": d["date"], "bout_id": d["bout_id"], "w": d["result_a"] == 0.0}),
    ]).sort_values(["date", "bout_id"])
    for f, g in long.groupby("fighter"):
        seq = ["W" if x else "L" for x in g["w"]]
        last = seq[-5:]
        streak = 1
        for r in reversed(seq[:-1]):
            if r != seq[-1]:
                break
            streak += 1
        rows.append((f, f"{last.count('W')}-{last.count('L')}", f"{seq[-1]}{streak}"))
    return pd.DataFrame(rows, columns=["fighter", "last5", "streak"]).set_index("fighter")


def durability(out: pd.DataFrame, as_of: pd.Timestamp, years: int = 10) -> pd.Series:
    """KO/TKO losses per UFC bout, each weighted by 1 - opponent danger.
    danger = 0.5 * min(opponent prior KO-win rate / 0.5, 1) + 0.5 * rank factor at fight time."""
    o = out.sort_values(["date", "bout_id"])
    ko_w, n = {}, {}
    pen, bouts = {}, {}
    for x in o.itertuples():
        a, b = x.fighter_a, x.fighter_b
        recent = (as_of - x.date).days / 365.25 <= years
        if recent:
            for f in (a, b):
                bouts[f] = bouts.get(f, 0) + 1
            if x.method == "KO/TKO" and x.result_a in (0.0, 1.0):
                w, l = (a, b) if x.result_a == 1.0 else (b, a)
                wpos = x.pos_a if w == a else x.pos_b
                power = (ko_w.get(w, 0) + 1) / (n.get(w, 0) + 2)
                elite = 1.0 if wpos <= 3 else 0.7 if wpos <= 7 else 0.4 if wpos <= 15 else 0.15
                danger = 0.5 * min(power / 0.5, 1.0) + 0.5 * elite
                pen[l] = pen.get(l, 0.0) + (1 - danger)
        for f, won in ((a, x.result_a == 1.0), (b, x.result_a == 0.0)):
            n[f] = n.get(f, 0) + 1
            if won and x.method == "KO/TKO":
                ko_w[f] = ko_w.get(f, 0) + 1
    return pd.Series({f: pen.get(f, 0.0) / c for f, c in bouts.items()}, name="ko_risk")


def head_to_head(board: pd.DataFrame, out: pd.DataFrame, as_of: pd.Timestamp, max_gap: int, max_years: float,
                 max_gap_recent: int | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Winner of the most recent meeting (within max_years) moves directly above the loser
    when he is ranked no more than max_gap spots below. Most recent meetings are applied last."""
    notes = []
    max_gap_recent = max_gap_recent or max_gap
    lf = last_five(out)
    negative_form = set(lf.index[lf["last5"].apply(lambda r: int(r.split("-")[1]) > int(r.split("-")[0]))])
    d = out[out["result_a"].isin([0.0, 1.0]) & ((as_of - out["date"]).dt.days <= max_years * 365.25)]
    d = d.sort_values("date")
    last_meeting = {}
    for x in d.itertuples():
        key = tuple(sorted((x.fighter_a, x.fighter_b)))
        old = (as_of - x.date).days > 365
        if old and getattr(x, "close", False):
            last_meeting.pop(key, None)          # a close win more than a year old settles nothing
            continue
        last_meeting[key] = (x.date, x.fighter_a if x.result_a == 1.0 else x.fighter_b)
    fixed = []
    for div, g in board.groupby("division"):
        order = list(g.sort_values("pos")["fighter"])
        for (f1, f2), (date, winner) in sorted(last_meeting.items(), key=lambda kv: kv[1][0]):
            if f1 in order and f2 in order:
                loser = f2 if winner == f1 else f1
                iw, il = order.index(winner), order.index(loser)
                gap_allowed = max_gap_recent if (as_of - date).days <= 365 else max_gap
                if winner in negative_form:
                    continue                     # a negative last five forfeits head-to-head lifts
                if 0 < iw - il <= gap_allowed:
                    order.insert(il, order.pop(iw))
                    notes.append(f"{div}: {winner} moved above {loser} (won {date.date()})")
        fixed.append(pd.DataFrame({"division": div, "fighter": order, "pos": range(1, len(order) + 1)}))
    fixed = pd.concat(fixed)
    return board.drop(columns=["pos"]).merge(fixed, on=["division", "fighter"]), notes


def assign_divisions(out: pd.DataFrame, as_of: pd.Timestamp, years: float = 3.0) -> pd.Series:
    """Two straight bouts in the same division settle it. Otherwise the division where the fighter
    has fought most in the last `years`; ties go to the division of the most recent win, then the
    most recent bout. Falls back to the latest ranked division."""
    rows = []
    d = out[out["division"].isin(RANKED_DIVISIONS)].sort_values(["date", "bout_id"])
    for side, other in (("fighter_a", 1.0), ("fighter_b", 0.0)):
        rows.append(pd.DataFrame({"fighter": d[side], "division": d["division"], "date": d["date"],
                                  "won": d["result_a"] == other}))
    long = pd.concat(rows).sort_values("date")
    res = {}
    for f, g in long.groupby("fighter"):
        if len(g) >= 2 and g["division"].iloc[-1] == g["division"].iloc[-2]:
            res[f] = g["division"].iloc[-1]          # two straight bouts in a division = a committed move
            continue
        rec = g[(as_of - g["date"]).dt.days <= years * 365.25]
        if rec.empty:
            res[f] = g["division"].iloc[-1]
            continue
        counts = rec["division"].value_counts()
        tied = list(counts[counts == counts.max()].index)
        if len(tied) == 1:
            res[f] = tied[0]
            continue
        wins = rec[rec["won"] & rec["division"].isin(tied)]
        res[f] = wins["division"].iloc[-1] if not wins.empty else rec[rec["division"].isin(tied)]["division"].iloc[-1]
    return pd.Series(res, name="division")


def title_cycle(cont: pd.DataFrame, out: pd.DataFrame, as_of: pd.Timestamp, tc: dict) -> tuple[pd.DataFrame, list[str]]:
    """A challenger who lost a title fight in the last `days` and has not won since is placed no
    higher than `min_position`: he is still close, but the champion is fighting someone else next.
    A champion who lost the belt is exempt (immediate rematches are common)."""
    notes = []
    t = out[out["title_fight"]].sort_values(["date", "bout_id"])
    holder: dict[str, str] = {}
    capped = {}
    for x in t.itertuples():
        if x.result_a not in (0.0, 1.0):
            continue
        winner = x.fighter_a if x.result_a == 1.0 else x.fighter_b
        loser = x.fighter_b if x.result_a == 1.0 else x.fighter_a
        defending = (not x.interim) and holder.get(x.division) == loser
        if not x.interim:
            holder[x.division] = winner
        if (as_of - x.date).days <= tc["days"] and not defending:
            capped[loser] = x.date
    # drop anyone who has won since the title loss
    d = out[out["result_a"].isin([0.0, 1.0])]
    for name, when in list(capped.items()):
        later = d[(d["date"] > when) & (((d["fighter_a"] == name) & (d["result_a"] == 1.0)) |
                                        ((d["fighter_b"] == name) & (d["result_a"] == 0.0)))]
        top10 = later["top10_win"].sum() if "top10_win" in later else 0
        if top10 >= tc.get("release_top10_wins", 1) or len(later) >= tc.get("release_wins", 2):
            capped.pop(name)                     # earned his way back
    beat_recently: dict[str, set] = {}
    for x in d[(as_of - d["date"]).dt.days <= 365].itertuples():
        w, l = (x.fighter_a, x.fighter_b) if x.result_a == 1.0 else (x.fighter_b, x.fighter_a)
        beat_recently.setdefault(w, set()).add(l)
    fixed = []
    for div, g in cont.groupby("division"):
        order = list(g.sort_values("pos")["fighter"])
        target = min(tc["min_position"] - 1, len(order) - 1)
        in_div = [n for n in order if n in capped]
        original = list(order)
        for _ in range(10):                      # repeat until both rules hold at once
            before = list(order)
            # 1) the top (min_position - 1) slots go to fighters without a recent title-fight loss
            # fighters a capped fighter beat in the last year cannot jump over him either
            held = capped.keys() | {n for c in in_div for n in beat_recently.get(c, set())}
            top, rest = [], list(order)
            while len(top) < target and any(n not in held for n in rest):
                nxt = next(n for n in rest if n not in held)
                rest.remove(nxt)
                top.append(nxt)
            order = top + rest
            # 2) anyone a capped fighter beat in the last year stays below him
            for c in in_div:
                j = order.index(c)
                for n in [n for n in order[:j] if n in beat_recently.get(c, set())]:
                    order.remove(n)
                    order.insert(order.index(c) + 1, n)
            if order == before:
                break
        for n in order:
            if order.index(n) != original.index(n) and (n in capped or original.index(n) < order.index(n)):
                why = (f"lost a title fight {capped[n].date()}; the champion fights someone else next" if n in capped
                       else "lost to a fighter moved by the title-cycle rule in the last year" if any(
                           n in beat_recently.get(c, set()) for c in in_div) else "shifted by the rule above")
                notes.append(f"{div}: {n} #{original.index(n) + 1} -> #{order.index(n) + 1} ({why})")
        fixed.append(pd.DataFrame({"division": div, "fighter": order, "pos": range(1, len(order) + 1)}))
    fixed = pd.concat(fixed)
    return cont.drop(columns=["pos"]).merge(fixed, on=["division", "fighter"]), notes


WIN_TIER_LIMITS = ((1, 2.0), (5, 1.5), (10, 1.0), (15, 0.5))   # rating position in the division -> win value


def rating_positions(f: pd.DataFrame, divisions: pd.Series, ratings: pd.Series) -> np.ndarray:
    """1 + number of eligible fighters (rows of f) in the same division whose raw rating exceeds `ratings`.
    999 when the rating is unknown. Retired or inactive opponents keep their last rating, so a win over a
    champion who left the sport at the top is not written down to nothing."""
    pos = np.full(len(divisions), 999.0)
    div_arr, r_arr = divisions.to_numpy(), ratings.to_numpy(dtype=float)
    for dv, g in f.groupby("division"):
        m = div_arr == dv
        if not m.any():
            continue
        sorted_r = np.sort(g["rating_raw"].to_numpy(dtype=float))
        rr = r_arr[m]
        p = (len(sorted_r) - np.searchsorted(sorted_r, rr, side="right")) + 1.0
        p[np.isnan(rr)] = 999.0
        pos[m] = p
    return pos


def hindsight_regrade(d: pd.DataFrame, f: pd.DataFrame, last: pd.DataFrame, hist: pd.DataFrame,
                      as_of: pd.Timestamp, hs: dict) -> pd.DataFrame:
    """Blend each result's fight-night grade with the opponent's later standing.

    mode now_rating:  the opponent's current rating, placed among today's eligible fighters in the bout's division.
    mode post_rating: the opponent's rating `post_years` after the bout (or today, if sooner), placed the same way,
                      so a decline many years later does not re-grade an old result.
    mode now_official: the opponent's official UFC rank as of the board date (unranked or retired counts as unranked).
    alpha_win / alpha_loss: weight on the fight-night grade (1.0 = no hindsight).
    Adds qw_value_then, qw_value_now, winner_pos_now; rewrites qw_value and quality_win."""
    d = d.copy()
    mode = hs["mode"]
    if mode == "now_rating":
        opp_rating = {"winner": last["rating"].reindex(d["loser"]).to_numpy(),
                      "loser": last["rating"].reindex(d["winner"]).to_numpy()}
    elif mode == "post_rating":
        post = float(hs.get("post_years", 2.0))
        h = hist.sort_values("date")
        by_f = {n: (g["date"].to_numpy(), g["rating"].to_numpy()) for n, g in h.groupby("fighter")}
        t_post = np.minimum((d["date"] + pd.to_timedelta(post * 365.25, unit="D")).to_numpy(), np.datetime64(as_of))

        def rating_at(names: pd.Series) -> np.ndarray:
            vals = np.full(len(names), np.nan)
            for i, (n, t) in enumerate(zip(names.to_numpy(), t_post)):
                arr = by_f.get(n)
                if arr is None:
                    continue
                j = np.searchsorted(arr[0], t, side="right") - 1
                if j >= 0:
                    vals[i] = arr[1][j]
            return vals
        opp_rating = {"winner": rating_at(d["loser"]), "loser": rating_at(d["winner"])}
    elif mode == "now_official":
        # the opponent's official UFC rank as of the board date (0 champion, 1-15, 99 unranked or retired); the
        # tiers below read a rating position and an official rank alike, since both count from the top
        from mmalab.official_ranks import OfficialRanks
        names = pd.concat([d["winner"], d["loser"]]).unique().tolist()
        official = OfficialRanks(names)

        def rank_now(opps: pd.Series) -> np.ndarray:
            return np.array([official.rank(n, dv, as_of) if official.rank(n, dv, as_of) is not None else 999.0
                             for n, dv in zip(opps.to_numpy(), d["division"].to_numpy())], dtype=float)
        loser_pos_now = rank_now(d["loser"])
        d["winner_pos_now"] = rank_now(d["winner"])
    else:
        raise ValueError(f"hindsight.mode {mode!r}: use now_rating, post_rating or now_official")
    if mode != "now_official":
        loser_pos_now = rating_positions(f, d["division"], pd.Series(opp_rating["winner"]))
        d["winner_pos_now"] = rating_positions(f, d["division"], pd.Series(opp_rating["loser"]))

    def win_value(pos: np.ndarray) -> np.ndarray:
        v = np.zeros(len(pos))
        for limit, val in reversed(WIN_TIER_LIMITS):
            v = np.where(pos <= limit, val, v)
        return v
    vet = (d["qw_value"].to_numpy() == 0.25).astype(float) * 0.25        # proven-veteran credit survives as the floor
    now = np.maximum(win_value(loser_pos_now), vet)
    aw = float(hs.get("alpha_win", 1.0))
    d["qw_value_then"] = d["qw_value"]
    d["qw_value_now"] = now
    d["qw_value"] = aw * d["qw_value_then"].to_numpy() + (1 - aw) * now
    d["quality_win"] = d["qw_value"] > 0
    return d


def _merge(base: dict, over: dict | None) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def tiered_form_penalty(out: pd.DataFrame, tiers: list, cap: float) -> pd.Series:
    """Per fighter: the sum over losses in the last five decided bouts of a cost set by the opponent's rank at the
    time (champion and top 5 cheapest, unranked dearest), capped. One opponent-aware form rule instead of record buckets."""
    d = out[out["result_a"].isin([0.0, 1.0])]
    long = pd.concat([
        pd.DataFrame({"fighter": d["fighter_a"], "date": d["date"], "bout_id": d["bout_id"], "lost": d["result_a"] == 0.0, "opp_pos": d["rank_b"]}),
        pd.DataFrame({"fighter": d["fighter_b"], "date": d["date"], "bout_id": d["bout_id"], "lost": d["result_a"] == 1.0, "opp_pos": d["rank_a"]}),
    ]).sort_values(["date", "bout_id"])
    last5 = long.groupby("fighter").tail(5)
    t = sorted((int(a), float(b)) for a, b in tiers)

    def cost(pos: float) -> float:
        for limit, c in t:
            if pos <= limit:
                return c
        return t[-1][1]
    pen = last5["lost"].astype(float) * last5["opp_pos"].fillna(999).map(cost)
    return pen.groupby(last5["fighter"]).sum().clip(upper=cap)


def bad_losses_last_five(out: pd.DataFrame, rank_above: int) -> pd.Series:
    """Per fighter: losses among the last five decided bouts to an opponent whose effective rank at the time was
    worse than `rank_above` (or unranked). A loss to a champion or top-10 fighter is not a bad loss."""
    d = out[out["result_a"].isin([0.0, 1.0])]
    long = pd.concat([
        pd.DataFrame({"fighter": d["fighter_a"], "date": d["date"], "bout_id": d["bout_id"], "lost": d["result_a"] == 0.0, "opp_pos": d["rank_b"]}),
        pd.DataFrame({"fighter": d["fighter_b"], "date": d["date"], "bout_id": d["bout_id"], "lost": d["result_a"] == 1.0, "opp_pos": d["rank_a"]}),
    ]).sort_values(["date", "bout_id"])
    last5 = long.groupby("fighter").tail(5)
    bad = last5["lost"] & (last5["opp_pos"].fillna(999) > rank_above)
    return bad.groupby(last5["fighter"]).sum()


def build(as_of: str | None = None, weights: dict | None = None, stability: bool = True,
          overrides: dict | None = None) -> tuple[pd.DataFrame, dict]:
    cfg = yaml.safe_load((CFG / "weights.yaml").read_text())
    rc = _merge(cfg["resume"], overrides)
    w = weights or rc["weights"]
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    as_of_ts = pd.Timestamp(as_of) if as_of else bouts["date"].max() + pd.Timedelta(days=1)
    bouts = bouts[bouts["date"] < as_of_ts]
    out, hist = run_resume(bouts, ResumeParams(**rc["engine"]))

    injured = layoffs_as_of(as_of_ts)          # roster files are read as of the board date, not today
    gone = exclusions_as_of(as_of_ts)
    inact = rc["inactivity"]

    last = hist.groupby("fighter").tail(1).set_index("fighter")
    f = pd.DataFrame({"rating_raw": last["rating"], "last_fight": last["date"]})
    f["division"] = assign_divisions(out, as_of_ts).reindex(f.index)
    for name, div in division_overrides_as_of(as_of_ts).items():
        if name in f.index:
            f.loc[name, "division"] = div
    # last appearance includes no-contests
    appear = pd.concat([out[["date", "fighter_a"]].rename(columns={"fighter_a": "fighter"}),
                        out[["date", "fighter_b"]].rename(columns={"fighter_b": "fighter"})]).groupby("fighter")["date"].max()
    f["days_since"] = (as_of_ts - appear.reindex(f.index)).dt.days
    f["injury"] = f.index.isin(set(injured))
    max_days = np.where(f["injury"], inact["injury_max_days"], inact["max_days"])
    f = f[(f["days_since"] <= max_days) & f["division"].isin(RANKED_DIVISIONS) & ~f.index.isin(set(gone))].copy()
    over = ((f["days_since"] - inact["grace_days"]) / (inact["max_days"] - inact["grace_days"])).clip(0, 1)
    f["inactivity_penalty"] = np.where(f["injury"], 0.0, over * inact["max_penalty_points"])
    f["rating"] = f["rating_raw"] - f["inactivity_penalty"]
    ad = rc.get("age_discount")
    if ad:
        # v1.2 candidate: the rating term is read as current ability, discounted by age. Measured Oct 20, 2026: fighters
        # ranked above their opponent won 45% of bouts when aged 35+ against 60% under 35 (EXP-2026-10-20-09).
        f["age"] = fighter_ages(f.index, as_of_ts)
        years_past = (f["age"] - float(ad["from_age"])).clip(lower=0).fillna(0.0)
        f["age_discount"] = years_past * float(ad["points_per_year"]) + years_past ** 2 * float(ad.get("points_per_year_squared", 0.0))
        f["rating"] = f["rating"] - f["age_discount"]

    # quality wins net of dominant losses, horizon weighted
    d = out[out["result_a"].isin([0.0, 1.0])].copy()
    d["winner"] = np.where(d["result_a"] == 1.0, d["fighter_a"], d["fighter_b"])
    d["loser"] = np.where(d["result_a"] == 1.0, d["fighter_b"], d["fighter_a"])
    d["age"] = (as_of_ts - d["date"]).dt.days / 365.25
    hz = {float(k): v for k, v in rc["horizons"].items()}
    d["hw"] = d["age"].apply(lambda a: horizon_weight(a, hz))
    hd = rc.get("horizon_decay")
    if hd:
        # continuous alternative to the step horizons: full credit for `full_years`, then exponential decay with time
        # constant `tau` (years), nothing after `max_years`
        age = d["age"].to_numpy()
        hw_exp = np.where(age <= float(hd["full_years"]), 1.0, np.exp(-(age - float(hd["full_years"])) / float(hd["tau"])))
        d["hw"] = np.where(age <= float(hd.get("max_years", 15)), hw_exp, 0.0)
    L = rc["ledger"]
    recent = d["age"] <= rc.get("decisive_loss_years", 3)
    # loss weight inside the window: "horizon" fades a loss on the win schedule (v1.0: identical to flat inside 3 years);
    # "flat" charges every loss inside the window in full
    d["lw"] = d["hw"] if L.get("loss_decay", "horizon") == "horizon" else 1.0
    hs = rc.get("hindsight") or {}
    if hs.get("mode"):
        # v1.1: results are re-graded in hindsight. The value of a win or the cost of a loss blends the opponent's
        # standing on fight night with his standing afterwards (rating position in the bout's division), so a win over
        # a fighter who then collapsed, or a loss to one who did, is worth what it turned out to be worth.
        d = hindsight_regrade(d, f, last, hist, as_of_ts, hs)
    d["qw_weighted"] = d["hw"] * d["qw_value"]
    qw = d[d["quality_win"]].groupby("winner")["qw_weighted"].sum() * L["quality_win"]
    proof = d[d["proof"]].groupby("loser")["hw"].sum() * L["proof_of_concept"]
    if L.get("loss_tiers"):
        # v1.1: a loss costs by the opponent's rank at the time (mirror of the win tiers); a blowout adds a little more
        tiers = sorted((int(a), float(b)) for a, b in L["loss_tiers"])

        def tier_cost(pos: float) -> float:
            for limit, cost in tiers:
                if pos <= limit:
                    return cost
            return tiers[-1][1]
        losses = d[recent & ~d["proof"]].copy()
        cost_then = losses["winner_pos"].fillna(999).map(tier_cost)
        if hs.get("mode"):
            al = float(hs.get("alpha_loss", 1.0))
            cost_now = losses["winner_pos_now"].fillna(999).map(tier_cost)
            losses["cost"] = al * cost_then + (1 - al) * cost_now
        else:
            losses["cost"] = cost_then
        losses["cost"] = losses["cost"] + np.where(losses["decisive_loss"], float(L.get("dominant_extra", 0.0)), 0.0)
        dl = losses[losses["decisive_loss"]].groupby("loser").apply(lambda g: float((g["lw"] * g["cost"]).sum()))
        wl = losses[~losses["decisive_loss"]].groupby("loser").apply(lambda g: float((g["lw"] * g["cost"]).sum()))
    else:
        dl = d[d["decisive_loss"] & recent].groupby("loser")["lw"].sum() * L["dominant_loss"]
        weak = d[recent & ~d["decisive_loss"] & ~d["proof"] & (d["winner_pos"] > rc["engine"].get("proof_top_n", 5))]
        wl = weak.groupby("loser")["lw"].sum() * L["loss_outside_top5"]
    q15 = d[d["quality_win"] & (d["age"] <= 15)].groupby("winner").size()
    t10 = d[d["top10_win"] & (d["age"] <= 15)].groupby("winner").size()
    t15 = d[d["top15_win"] & (d["age"] <= 15)].groupby("winner").size()
    parts = pd.concat([qw.rename("qw"), proof.rename("proof"), dl.rename("dl"), wl.rename("wl")], axis=1).fillna(0)
    parts = parts.reindex(f.index).fillna(0)
    # the ledger: quality wins + proof-of-concept losses - blowout losses - losses outside the top 5
    f["quality_wins"] = parts["qw"] + parts["proof"] - parts["dl"] - parts["wl"]
    f["ledger_detail"] = [f"+{a:.1f} QW +{b:.1f} proof -{c:.1f} blowout -{e:.1f} weak"
                          for a, b, c, e in parts[["qw", "proof", "dl", "wl"]].itertuples(index=False)]
    f["quality_wins_15y"] = q15.reindex(f.index).fillna(0).astype(int)
    f["top10_wins_15y"] = t10.reindex(f.index).fillna(0).astype(int)
    f["top15_wins_15y"] = t15.reindex(f.index).fillna(0).astype(int)
    ent = rc.get("entrenched", {"top10_wins": 4, "top15_wins": 5})
    f["entrenched"] = (f["top10_wins_15y"] >= ent["top10_wins"]) | (f["top15_wins_15y"] >= ent["top15_wins"])
    ufc_bouts = pd.concat([out["fighter_a"], out["fighter_b"]]).value_counts()
    f["ufc_bouts"] = ufc_bouts.reindex(f.index).fillna(0).astype(int)
    f = f.join(last_five(out)).join(durability(out, as_of_ts))
    f = f.reset_index().rename(columns={"index": "fighter"})

    fp = {str(k): float(v) for k, v in rc["form_penalty"].items()}
    f["form_penalty"] = f["last5"].map(lambda r: fp.get(r, 0.0)).fillna(0.0)
    ft = rc.get("form_loss_tiers")
    if ft:
        # v1.1 candidate: replaces the record buckets with one opponent-aware rule
        f["form_penalty"] = tiered_form_penalty(out, ft["tiers"], float(ft["cap"])).reindex(f["fighter"]).fillna(0.0).to_numpy()
    fb = rc.get("form_bad_loss")
    if fb:
        # v1.1 add-on: each loss in the last five to an opponent outside the top `rank_above` costs extra, so a losing run
        # against elite opposition is treated differently from one against mid-card opposition
        bad = bad_losses_last_five(out, int(fb["rank_above"])).reindex(f["fighter"]).fillna(0).to_numpy()
        f["form_penalty"] = f["form_penalty"] + np.minimum(bad * float(fb["per_loss"]), float(fb["cap"]))

    champs = champions(out, as_of_ts)
    interim = interim_as_of(as_of_ts)
    for div, name in list(champs.items()) + list(interim.items()):
        f.loc[f["fighter"] == name, "division"] = div      # a title holder is ranked in his title's division
    f["champion"] = f.apply(lambda r: champs.get(r["division"]) == r["fighter"], axis=1)
    f["interim"] = f.apply(lambda r: interim.get(r["division"]) == r["fighter"], axis=1)
    reserved = reserved_as_of(as_of_ts)
    for div, name in reserved.items():
        f.loc[f["fighter"] == name, "division"] = div
    f["reserved"] = f.apply(lambda r: reserved.get(r["division"]) == r["fighter"], axis=1)

    def score(frame: pd.DataFrame, wts: dict) -> pd.DataFrame:
        parts = []
        for div, g in frame.groupby("division"):
            g = g.copy()
            g["rating_term"] = wts["rating"] * idr_scale(g["rating"])
            g["ledger_term"] = wts["quality_wins"] * idr_scale(g["quality_wins"])
            g["score"] = g["rating_term"] + g["ledger_term"] - g["form_penalty"]
            cont = g[~g["champion"] & ~g["interim"] & ~g["reserved"]].sort_values("score", ascending=False)
            g["pos"] = np.nan
            g.loc[cont.index, "pos"] = range(1, len(cont) + 1)
            parts.append(g)
        return pd.concat(parts)

    board = score(f, w)
    titled = board[board["pos"].isna()].copy()
    cont = board[board["pos"].notna()].copy()
    cont["pos_score"] = cont["pos"]
    h2h = rc["head_to_head"]
    use_solver = rc.get("placement", "sequential") == "solver"
    placement_report: dict = {}
    if use_solver:
        # v1.1: the head-to-head and title-cycle rules solved as one constrained order (src/mmalab/placement.py), so
        # the result no longer depends on the order the rules are applied in; the sequential loop stays for v1.0
        from mmalab.placement import apply_to_board, build_context
        ctx = build_context(out, as_of_ts, rc)
        cont, h2h_notes, placement_report = apply_to_board(cont, out, as_of_ts, rc, ctx)
        cont["pos_h2h"] = cont["pos"]
    else:
        cont, h2h_notes = head_to_head(cont, out, as_of_ts, h2h["max_gap"], h2h["max_years"],
                                       h2h.get("max_gap_recent"))
        cont["pos_h2h"] = cont["pos"]
        cont, cycle_notes = title_cycle(cont, out, as_of_ts, rc["title_cycle"])
        h2h_notes += cycle_notes

    # weight-sensitivity band: 10th to 90th percentile of the FINAL position (score order, then the
    # head-to-head and title-cycle rules, exactly as published) across weight vectors drawn near the
    # chosen weights. It measures how much the placement depends on the 70/30 choice, not skill
    # uncertainty, so the published rank always lies inside its own band.
    if stability:
        rng = np.random.default_rng(7)
        keys = list(w)
        base = np.array([w[k] for k in keys])
        draws = []
        for _ in range(rc["stability_draws"]):
            wv = dict(zip(keys, rng.dirichlet(base * rc["stability_concentration"])))
            s = score(f, wv)
            c = s[s["pos"].notna()].copy()
            if use_solver:
                c, _, _ = apply_to_board(c, out, as_of_ts, rc, ctx)
            else:
                c, _ = head_to_head(c, out, as_of_ts, h2h["max_gap"], h2h["max_years"], h2h.get("max_gap_recent"))
                c, _ = title_cycle(c, out, as_of_ts, rc["title_cycle"])
            draws.append(c[["division", "fighter", "pos"]])
        dd = pd.concat(draws).groupby(["division", "fighter"])["pos"].quantile([0.1, 0.9]).unstack()
        dd.columns = ["rank_p10", "rank_p90"]
        cont = cont.merge(dd.reset_index(), on=["division", "fighter"], how="left")
    else:
        cont["rank_p10"] = cont["rank_p90"] = cont["pos"]
    titled["rank_p10"] = titled["rank_p90"] = 0
    board = pd.concat([titled, cont], ignore_index=True)
    board["rank"] = board["pos"].fillna(0).astype(int)
    board["slot"] = np.where(board["champion"], 0, np.where(board["interim"], 1, np.where(board["reserved"], 2, 3)))
    board = board.sort_values(["division", "slot", "rank"])
    # measurement uncertainty (Glicko-1 deviation track, config/uncertainty.yaml): display and audit only, never ordering
    board = board.join(board_bands(out, board, as_of_ts, z=1.0))

    overrides = division_overrides_as_of(as_of_ts)
    board["division_source"] = np.where(board["champion"] | board["interim"] | board["reserved"], "title holder or reserved",
                                np.where(board["fighter"].isin(list(overrides)), "override (config)", "fight record"))
    def why(r) -> str:
        if r["champion"] or r["interim"]:
            return "title holder"
        if r["reserved"]:
            return "reserved: vacated with injury, owed a title shot"
        steps = [f"score order #{int(r['pos_score'])}"]
        if use_solver:
            if r["rank"] != r["pos_score"]:
                steps.append(f"placement rules -> #{int(r['rank'])}")
            return "; ".join(steps)
        if r["pos_h2h"] != r["pos_score"]:
            steps.append(f"head-to-head -> #{int(r['pos_h2h'])}")
        if r["rank"] != r["pos_h2h"]:
            steps.append(f"title cycle -> #{int(r['rank'])}")
        return "; ".join(steps)
    board["placement"] = board.apply(why, axis=1)

    # columns expected by publish.py / compare.py
    board["record_3y"] = board["last5"]
    board["top15_wins"] = board["top10_wins_15y"]   # site column: top-10 wins in 15 years
    meta = {"as_of": as_of_ts - pd.Timedelta(days=1), "weights": w, "h2h": h2h_notes, "champs": champs,
            "interim": interim, "placement": placement_report}
    return board, meta


def main(as_of: str | None = None) -> None:
    cfg = yaml.safe_load((CFG / "weights.yaml").read_text())
    board, meta = build(as_of)
    OUT.mkdir(exist_ok=True)
    from mmalab.history import snapshot
    snapshot(board, meta["as_of"])          # keeps the weekly history for movement arrows and validation
    board.to_csv(OUT / "composite_rankings_full.csv", index=False)
    size = cfg["board_size"]
    top = board[board["rank"] <= size]
    cols = ["division", "rank", "fighter", "champion", "interim", "reserved", "score", "rating", "quality_wins",
            "top10_wins_15y", "top15_wins_15y", "entrenched", "last5", "streak", "days_since", "injury", "ko_risk",
            "rank_p10", "rank_p90"]
    top[cols].round(3).to_csv(OUT / "composite_top15_by_division.csv", index=False)

    lines = [f"# Divisional boards as of {meta['as_of'].date()}",
             f"weights: {meta['weights']}; stability = 10th-90th percentile position across nearby weights", ""]
    for div in RANKED_DIVISIONS:
        g = top[top["division"] == div]
        if g.empty:
            continue
        lines.append(f"\n## {div}" + ("   (title vacant)" if div not in meta["champs"] and div not in meta["interim"] else ""))
        for r in g.itertuples():
            label = " C" if r.champion else ("IC" if r.interim else (" R" if r.reserved else f"{r.rank:>2}"))
            inj = " (injury layoff)" if r.injury else ""
            lines.append(f"{label}. {r.fighter:<26} score {r.score:+.2f}  rating {r.rating:6.0f}  last5 {r.last5:<4} "
                         f"ledger {r.quality_wins:4.1f} (T10 {int(r.top10_wins_15y)}, T15 {int(r.top15_wins_15y)}{' E' if r.entrenched else ''})  "
                         f"days {int(r.days_since):>3}{inj}  band [{int(r.rank_p10)}-{int(r.rank_p90)}]")
    lines += ["", "## Head-to-head moves applied"] + [f"- {n}" for n in meta["h2h"]]
    (OUT / "composite_boards.md").write_text("\n".join(lines))
    audit_cols = ["division", "rank", "fighter", "placement", "division_source", "score", "rating_term",
                  "ledger_term", "form_penalty", "rating", "rating_raw", "inactivity_penalty", "injury",
                  "quality_wins", "ledger_detail", "top10_wins_15y", "top15_wins_15y", "entrenched", "last5", "streak",
                  "days_since", "ko_risk", "rank_p10", "rank_p90"]
    top[[c for c in audit_cols if c in top.columns]].round(3).to_csv(OUT / "audit_top30.csv", index=False)
    print("\n".join(lines))


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
