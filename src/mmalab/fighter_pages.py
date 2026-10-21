"""
fighter_pages.py - One descriptive profile page per fighter on the registered board, plus an index.

Writes docs/fighters/<slug>.html for every row of outputs/composite_rankings_full.csv (champions, interim and
reserved holders, every ranked contender) and docs/fighters/index.html. A profile is for human judgment and
says so near the top: the resume rank is what has been earned, the statistics beside it are context, not a
prediction (EXP-2026-10-20-14 found career statistics add nothing reliable to age, layoff and experience).

Page order: header (division, REAL v1.0 registered rank and v1.1 shadow rank, weight band, Glicko-1 deviation
as a measurement note, tale of the tape); why he is ranked here (score decomposition, ledger, placement string
and a plain sentence built from them); last ten bouts with the opponent's official rank at the time and the
predictive model's pre-fight probability; career statistics with division percentiles and two inline SVG
charts (board position since Oct 2023, predictive rating by bout); descriptive context flags; publish.footer().

Sources, each loaded once in load_sources(): outputs/composite_rankings_full.csv (v1.0), outputs/boards/v1.1/
(shadow), outputs/history/board_*.csv (weekly snapshots), data/processed/{bouts_with_stats, bouts_rated,
elo_history, fighters}.csv, career_stats.features_as_of (statistics as of the data date) and
official_ranks.OfficialRanks (opponent rank at fight time).

Public surface: slug(name), unique_slugs(names), build_profiles(), render(profile), render_index(profiles,
as_of), main(). publish.py links a board row to fighters/<slug(name)>.html. Style follows publish.py: its CSS,
system font, light theme with the dark-mode media query, no external assets, no JavaScript, no em dashes.
"""
from __future__ import annotations

import html
import math
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from mmalab import publish
from mmalab.career_stats import features_as_of, load_fighters
from mmalab.official_ranks import OfficialRanks
from mmalab.rankings import RANKED_DIVISIONS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
PROC = ROOT / "data" / "processed"
DOCS = ROOT / "docs"
PAGES = DOCS / "fighters"
HIST = OUT / "history"
BOARD_V10 = OUT / "composite_rankings_full.csv"
BOARD_V11 = OUT / "boards" / "v1.1" / "composite_rankings_full.csv"

PROVISIONAL_MAX_BOUTS = publish.PROVISIONAL_MAX_BOUTS
LAST_BOUTS = 10
NEWCOMER_RD = 290          # median Glicko-1 deviation after one UFC bout (EXP-2026-10-20-10)
LAYOFF_FLAG_DAYS = 365
KO_WINDOW_DAYS = 90        # longest of the Association of Ringside Physicians minimum suspensions (30 / 60 / 90)
MARKER_LIMIT = 60          # a series with more points than this gets hover columns instead of a marker per point
EM_DASH = chr(0x2014)      # never written to a page; any one that slips in through a data string becomes a hyphen

DISCLAIMER = ("Descriptive profile. The resume rank is what has been earned; these statistics are context, not a "
              "prediction. A test on Oct 20, 2026 found that career statistics add nothing reliable to age, layoff and "
              "experience as predictors of the next result (experiments/REGISTER.md, EXP-2026-10-20-14).")
# the pages reuse publish.CSS and add only what their own tables and the index need
EXTRA_CSS = ("td.nw,th.nw{white-space:nowrap}table.stats td:first-child{width:44%}table.stats th.grp{padding-top:14px}"
             "ul.cols{columns:3 240px;column-gap:24px;list-style:none;padding-left:0}ul.cols li{break-inside:avoid}")

# favourite's win rate by age band on the board's own history, EXP-2026-10-20-09 (3,748 bouts, 2014 to 2026)
AGE_BANDS = [(30, "under 30", "64%"), (33, "30 to 32", "59%"), (36, "33 to 35", "57%"), (math.inf, "36 and over", "42 to 46%")]
AGE_RATES = "64% of bouts when under 30, 59% at 30 to 32, 57% at 33 to 35 and 42 to 46% at 36 and over"

METHOD_LABEL = {"U-DEC": "unanimous decision", "S-DEC": "split decision", "M-DEC": "majority decision",
                "KO/TKO": "KO/TKO", "SUB": "submission", "NC": "no contest", "DQ": "disqualification", "OTHER": "other"}

# statistics that get a division percentile (column in career_stats.features_as_of, or added in build_profiles)
STAT_COLS = ["slpm", "sig_acc", "kd_for_per15", "finish_rate_for", "sapm", "sig_def", "kd_against_per15",
             "cum_sig_absorbed", "ko_losses", "sub_losses", "ko_risk", "td_avg", "td_def", "ctrl_share",
             "grappling_share", "debut_age", "ufc_years", "n_bouts", "minutes", "bouts_per_year", "layoff_days", "age"]
# rendered groups: (heading, [(column, label, format)]); None format rows are composed by hand
STAT_GROUPS = [
    ("Output", [("slpm", "Significant strikes landed per minute", "{:.2f}"),
                ("sig_acc", "Significant strike accuracy", "{:.0%}"),
                ("kd_for_per15", "Knockdowns scored per 15 minutes", "{:.2f}"),
                ("finish_rate_for", "Share of wins by finish", "{:.0%}")]),
    ("Defence and damage", [("sapm", "Significant strikes absorbed per minute", "{:.2f}"),
                            ("sig_def", "Significant strike defence", "{:.0%}"),
                            ("kd_against_per15", "Knockdowns suffered per 15 minutes", "{:.2f}"),
                            ("cum_sig_absorbed", "Significant strikes absorbed, career", "{:,.0f}"),
                            ("ko_losses", "KO/TKO losses", None),
                            ("sub_losses", "Submission losses", "{:.0f}"),
                            ("ko_risk", "KO/TKO losses per bout over 10 years, each weighted down by the finisher's danger", "{:.3f}")]),
    ("Grappling", [("td_avg", "Takedowns landed per 15 minutes", "{:.2f}"),
                   ("td_def", "Takedown defence", "{:.0%}"),
                   ("ctrl_share", "Share of cage time in control", "{:.0%}"),
                   ("grappling_share", "Share of significant strikes landed in the clinch or on the ground", "{:.0%}"),
                   ("style", "Style", None)]),
    ("Career stage", [("age", "Age", "{:.1f}"),
                      ("debut_age", "Age at UFC debut", "{:.1f}"),
                      ("ufc_years", "Years since UFC debut", "{:.1f}"),
                      ("n_bouts", "UFC bouts", "{:.0f}"),
                      ("minutes", "Cage time, minutes", "{:,.0f}"),
                      ("bouts_per_year", "Bouts per year, last three years", "{:.1f}"),
                      ("layoff_days", "Days since last bout", "{:.0f}")]),
]

_TRANSLIT = str.maketrans({"ø": "o", "Ø": "o", "ł": "l", "Ł": "l", "ß": "ss", "æ": "ae", "Æ": "ae", "œ": "oe",
                           "Œ": "oe", "đ": "d", "Đ": "d", "ð": "d", "Ð": "d", "þ": "th", "Þ": "th"})


# ---------------------------------------------------------------------------
# slugs

def slug(name: str) -> str:
    """URL slug for a fighter name: lower-case ASCII letters and digits joined by single hyphens.

    Accents are folded (jose for José), apostrophes and periods are dropped (omalley, jr), every other run of
    characters becomes one hyphen, so the parenthetical suffixes the data uses for same-name fighters survive as
    words: "Bruno Silva (Blindado)" -> "bruno-silva-blindado". Stable: the same name always gives the same slug;
    two names collide only when they differ by case, accents or punctuation alone (see unique_slugs).
    """
    s = unicodedata.normalize("NFKD", str(name)).translate(_TRANSLIT)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).encode("ascii", "ignore").decode().lower()
    s = re.sub("['" + chr(0x2019) + ".]", "", s)       # straight or curly apostrophe, period
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "fighter"


def unique_slugs(names: Iterable[str]) -> dict[str, str]:
    """Name -> slug for a set of names. Names sharing a slug are taken in sorted order; the second and later get
    -2, -3, ... appended, so the mapping is deterministic whatever the input order."""
    out: dict[str, str] = {}
    taken: set[str] = set()
    for name in sorted({str(n) for n in names}):
        base = slug(name)
        s, k = base, 2
        while s in taken:
            s, k = f"{base}-{k}", k + 1
        out[name] = s
        taken.add(s)
    return out


# ---------------------------------------------------------------------------
# data

def _read_board(path: Path) -> pd.DataFrame:
    """A board CSV with its flag columns coerced to bool (they round-trip through CSV as 'True' / 'False')."""
    b = pd.read_csv(path)
    for c in ("champion", "interim", "reserved", "entrenched", "injury"):
        if c in b.columns:
            b[c] = b[c].astype(str).str.lower().isin(["true", "1"])
    return b


def _read_history(root: Path = HIST) -> pd.DataFrame:
    """Every weekly snapshot as one frame: date, division, fighter, position (0 = title holder or reserved)."""
    frames = []
    for p in sorted(root.glob("board_*.csv")):
        d = pd.read_csv(p, usecols=["division", "fighter", "position"])
        d["date"] = pd.Timestamp(p.stem.split("_", 1)[1])
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["division", "fighter", "position", "date"])
    return pd.concat(frames, ignore_index=True)


def load_sources() -> dict:
    """Load every input once. Keys: board, shadow (or None), bouts, p_a (bout_id -> p_a), elo, fighters,
    history, features, official, as_of (data date), stats_as_of (the day after, so the last bout counts)."""
    board = _read_board(BOARD_V10)
    shadow = _read_board(BOARD_V11) if BOARD_V11.exists() else None
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    as_of = bouts["date"].max()
    stats_as_of = as_of + pd.Timedelta(days=1)
    rated_path = PROC / "bouts_rated.csv"
    p_a: dict[int, float] = {}
    if rated_path.exists():
        rr = pd.read_csv(rated_path, usecols=["bout_id", "p_a"])
        p_a = dict(zip(rr["bout_id"].astype(int), rr["p_a"].astype(float)))
    elo_path = PROC / "elo_history.csv"
    elo = pd.read_csv(elo_path, parse_dates=["date"]) if elo_path.exists() else pd.DataFrame(
        columns=["fighter", "date", "bout_id", "division", "rating", "ufc_fights"])
    fighters = load_fighters()
    fighters = (fighters.drop_duplicates("fighter").set_index("fighter") if fighters is not None
                else pd.DataFrame(columns=["height_in", "reach_in", "stance", "dob"]))
    names = pd.concat([bouts["fighter_a"], bouts["fighter_b"]]).dropna().unique().tolist()
    official = None if {"official_a", "official_b"} <= set(bouts.columns) else OfficialRanks(names)
    return {"board": board, "shadow": shadow, "bouts": bouts, "p_a": p_a, "elo": elo, "fighters": fighters,
            "history": _read_history(), "features": features_as_of(bouts, stats_as_of), "official": official,
            "as_of": as_of, "stats_as_of": stats_as_of}


# ---------------------------------------------------------------------------
# small formatting helpers

def _f(x) -> float | None:
    """A plain float, or None for NaN / missing (keeps every profile JSON-like)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, ..."""
    n = int(n)
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _rank_label(row) -> str:
    """champion / interim champion / reserved / #n, as the board rows are labelled on the site."""
    if row["champion"]:
        return "champion"
    if row["interim"]:
        return "interim champion"
    if row["reserved"]:
        return "reserved"
    return f"#{int(row['rank'])}"


def _official_label(v: float | None) -> str:
    """0 champion, 1-15 ranked, 99 unranked, None no official board for that date or division."""
    if v is None:
        return "n/a"
    if v == 0:
        return "C"
    if v >= 99:
        return "unranked"
    return f"#{int(v)}"


def _result_letter(result_for: float | None) -> str:
    """W / L / D from the fighter's own result (1, 0, 0.5); NC when the bout had no result."""
    if result_for is None:
        return "NC"
    return {1.0: "W", 0.0: "L", 0.5: "D"}.get(result_for, "NC")


def _height(inches: float | None) -> str:
    if inches is None:
        return "unknown"
    ft, rem = divmod(int(round(inches)), 12)
    return f"{ft} ft {rem} in ({inches * 2.54:.0f} cm)"


def _reach(inches: float | None) -> str:
    return "unknown" if inches is None else f"{inches:.0f} in ({inches * 2.54:.0f} cm)"


def _parse_ledger(detail: str) -> dict[str, float]:
    """'+5.2 QW +0.0 proof -1.0 blowout -0.0 weak' -> the four magnitudes (zeros when the string is odd)."""
    m = re.match(r"\+?([\d.]+) QW \+?([\d.]+) proof -?([\d.]+) blowout -?([\d.]+) weak", str(detail or ""))
    keys = ("qw", "proof", "blowout", "weak")
    if not m:
        return dict.fromkeys(keys, 0.0)
    return dict(zip(keys, (float(x) for x in m.groups())))


# ---------------------------------------------------------------------------
# profiles

def _board_entry(row, div_board: pd.DataFrame) -> dict:
    """The board-derived part of a profile (one board version)."""
    titled = bool(row["champion"] or row["interim"] or row["reserved"])
    rating_order = int((div_board["rating"] > row["rating"]).sum()) + 1
    champ = div_board[div_board["champion"]]
    champ_rating = _f(champ["rating"].iloc[0]) if not champ.empty else None
    return {"label": _rank_label(row), "rank": int(row["rank"]), "champion": bool(row["champion"]),
            "interim": bool(row["interim"]), "reserved": bool(row["reserved"]),
            "band": None if titled else f"{int(row['rank_p10'])}-{int(row['rank_p90'])}",
            "score": _f(row["score"]), "rating_term": _f(row["rating_term"]), "ledger_term": _f(row["ledger_term"]),
            "form_penalty": _f(row["form_penalty"]) or 0.0, "rating": _f(row["rating"]),
            "rating_raw": _f(row["rating_raw"]), "inactivity_penalty": _f(row["inactivity_penalty"]) or 0.0,
            "injury": bool(row["injury"]), "rd": _f(row.get("rd")), "ufc_bouts": int(row["ufc_bouts"]),
            "last5": str(row["last5"]), "streak": str(row["streak"]), "days_since": int(row["days_since"]),
            "last_fight": str(row["last_fight"]), "quality_wins": _f(row["quality_wins"]) or 0.0,
            "ledger_detail": str(row["ledger_detail"]), "entrenched": bool(row["entrenched"]),
            "quality_wins_15y": int(row["quality_wins_15y"]), "top10_wins_15y": int(row["top10_wins_15y"]),
            "top15_wins_15y": int(row["top15_wins_15y"]), "placement": str(row["placement"]),
            "division_source": str(row.get("division_source", "fight record")),
            "rating_order": rating_order, "division_size": int(len(div_board)), "champion_rating": champ_rating,
            "ko_risk": _f(row.get("ko_risk"))}


def _bout_rows(name: str, mine: pd.DataFrame, src: dict, slugs: dict[str, str]) -> list[dict]:
    """The fighter's last LAST_BOUTS bouts, most recent first."""
    official = src["official"]
    rows = []
    for x in mine.sort_values(["date", "bout_id"], ascending=False).head(LAST_BOUTS).itertuples():
        is_a = x.fighter_a == name
        opp = x.fighter_b if is_a else x.fighter_a
        res = _f(x.result_a)
        res_for = None if res is None else (res if is_a else 1.0 - res)
        if official is None:
            off = _f(getattr(x, "official_b" if is_a else "official_a"))
        else:
            off = official.rank(opp, x.division, x.date)
        p = src["p_a"].get(int(x.bout_id))
        p_for = None if p is None or math.isnan(p) else (p if is_a else 1.0 - p)
        secs = _f(x.time_sec)
        rows.append({"date": str(pd.Timestamp(x.date).date()), "event": str(x.event), "division": str(x.division),
                     "opponent": opp, "opponent_slug": slugs.get(opp), "opp_rank": _official_label(off),
                     "result": _result_letter(res_for), "method": METHOD_LABEL.get(str(x.method), str(x.method)),
                     "round": int(x.round) if _f(x.round) is not None else None,
                     "time": None if secs is None else f"{int(secs) // 60}:{int(secs) % 60:02d}",
                     "title_fight": bool(x.title_fight), "p": p_for})
    return rows


def _rating_rows(name: str, elo: pd.DataFrame | None, bout_info: dict[int, tuple]) -> list[dict]:
    """The predictive rating after each of the fighter's UFC bouts, oldest first, with opponent and result for the tooltip."""
    if elo is None or elo.empty:
        return []
    rows = []
    for x in elo.sort_values(["date", "bout_id"]).itertuples():
        info = bout_info.get(int(x.bout_id))
        opp, res = (None, None)
        if info:
            a, b, ra = info
            opp = b if a == name else a
            res = _result_letter(None if ra is None else (ra if a == name else 1.0 - ra))
        rows.append({"date": str(pd.Timestamp(x.date).date()), "rating": round(float(x.rating), 1),
                     "opponent": opp, "result": res})
    return rows


def build_profiles(src: dict | None = None) -> list[dict]:
    """One JSON-like dict per fighter on the registered board, in board order (division, slot, rank)."""
    src = src or load_sources()
    board, shadow, bouts = src["board"], src["shadow"], src["bouts"]
    as_of = src["as_of"]
    slugs = unique_slugs(board["fighter"])
    feat = src["features"].reindex(board["fighter"]).copy()
    feat["debut_age"] = feat["age"] - feat["ufc_years"]
    feat["ko_risk"] = board["ko_risk"].to_numpy() if "ko_risk" in board.columns else np.nan
    feat["division"] = board["division"].to_numpy()
    pct = feat.groupby("division")[STAT_COLS].rank(pct=True, method="max") * 100.0
    shadow_rows = {} if shadow is None else {r["fighter"]: r for _, r in shadow.iterrows()}
    shadow_divs = {} if shadow is None else {d: g for d, g in shadow.groupby("division")}
    hist = src["history"]
    hist_by = {n: g for n, g in hist.groupby("fighter")} if not hist.empty else {}
    snap_dates = sorted(hist["date"].unique()) if not hist.empty else []
    elo_by = {n: g for n, g in src["elo"].groupby("fighter")} if not src["elo"].empty else {}
    bout_info = {int(x.bout_id): (x.fighter_a, x.fighter_b, _f(x.result_a)) for x in bouts.itertuples()}
    long_a = bouts[["bout_id", "fighter_a"]].rename(columns={"fighter_a": "fighter"})
    long_b = bouts[["bout_id", "fighter_b"]].rename(columns={"fighter_b": "fighter"})
    by_fighter = pd.concat([long_a, long_b]).groupby("fighter")["bout_id"].apply(set).to_dict()
    bouts_by_id = bouts.set_index("bout_id", drop=False).rename_axis("bid")
    fighters = src["fighters"]

    profiles = []
    for div, g in board.groupby("division", sort=False):
        for _, row in g.iterrows():
            name = row["fighter"]
            mine = bouts_by_id.loc[sorted(by_fighter.get(name, ()))] if by_fighter.get(name) else bouts.iloc[0:0]
            fe = feat.loc[name] if name in feat.index else pd.Series(dtype=float)
            pc = pct.loc[name] if name in pct.index else pd.Series(dtype=float)
            stats = {c: {"value": _f(fe.get(c)), "pct": (None if _f(pc.get(c)) is None else int(round(float(pc[c]))))}
                     for c in STAT_COLS}
            st = fe.get("style")
            style = st if isinstance(st, str) else "unknown"
            tape = fighters.loc[name] if name in fighters.index else pd.Series(dtype=object)
            dob = tape.get("dob")
            dob = None if dob is None or pd.isna(dob) else str(pd.Timestamp(dob).date())
            stance = tape.get("stance")
            v11 = None
            if name in shadow_rows:
                v11 = _board_entry(shadow_rows[name], shadow_divs[shadow_rows[name]["division"]])
            h = hist_by.get(name)
            base = re.sub(r"\s*\(.*\)\s*$", "", name)
            if base != name and not ((board["fighter"] == base) & (board["division"] == div)).any():
                # snapshots written before the same-name split carry the plain name in this division
                old = hist_by.get(base)
                if old is not None:
                    old = old[old["division"] == div]
                    h = old if h is None else pd.concat([old, h]).drop_duplicates("date", keep="last")
            rank_history = [] if h is None else [
                {"date": str(pd.Timestamp(x.date).date()), "position": int(x.position), "division": str(x.division)}
                for x in h.sort_values("date").itertuples()]
            # last appearance including no contests (what days_since counts from); the board's last_fight is the last rated bout
            last_bout = None if mine.empty else str(pd.Timestamp(mine["date"].max()).date())
            profiles.append({
                "name": name, "slug": slugs[name], "division": div, "as_of": str(as_of.date()), "last_bout": last_bout,
                "snapshot_dates": [str(pd.Timestamp(d).date()) for d in snap_dates],
                "v10": _board_entry(row, g), "v11": v11,
                "tape": {"age": _f(fe.get("age")), "dob": dob, "height_in": _f(tape.get("height_in")),
                         "reach_in": _f(tape.get("reach_in")),
                         "stance": None if stance is None or pd.isna(stance) else str(stance)},
                "stats": stats, "style": style, "td_rate": _f(fe.get("td_rate")),
                "last_ko_loss_days": _f(fe.get("last_ko_loss_days")), "ko_losses_3y": int(_f(fe.get("ko_losses_3y")) or 0),
                "bouts": _bout_rows(name, mine, src, slugs), "rank_history": rank_history,
                "rating_history": _rating_rows(name, elo_by.get(name), bout_info),
            })
    return profiles


# ---------------------------------------------------------------------------
# prose

def pronouns(division: str) -> tuple[str, str, str]:
    """(subject, object, possessive) for the prose: she/her/her in the women's divisions, he/him/his elsewhere."""
    return ("she", "her", "her") if str(division).startswith("Women") else ("he", "him", "his")


def _rating_phrase(v: dict) -> str:
    """Where the resume rating stands among the division's board fighters."""
    r, order, n = v["rating"], v["rating_order"], v["division_size"]
    if r is None:
        return "No rating is recorded"
    if order == 1:
        return f"Rating {r:,.0f} is the division's highest"
    champ_top = v["champion_rating"] is not None and v["champion_rating"] >= r and not (v["champion"] or v["interim"])
    if order == 2 and champ_top:
        return f"Rating {r:,.0f} is the division's highest below the champion"
    return f"Rating {r:,.0f} is the division's {_ordinal(order)} highest of {n} board fighters"


def _ledger_phrase(v: dict, obj: str = "him") -> str:
    """The quality ledger spelled out from ledger_detail, with the 15-year quality-win counts."""
    parts = _parse_ledger(v["ledger_detail"])
    bits = []
    if parts["qw"]:
        bits.append(f"+{parts['qw']:.1f} from quality wins")
    if parts["proof"]:
        bits.append(f"+{parts['proof']:.1f} from close losses to top-5 fighters")
    if parts["blowout"]:
        bits.append(f"less {parts['blowout']:.1f} for blowout losses")
    if parts["weak"]:
        bits.append(f"less {parts['weak']:.1f} for other losses outside the top 5")
    inside = f" ({', '.join(bits)}; losses count for three years)" if bits else " (no quality wins or recent losses on the ledger)"
    q = v["quality_wins_15y"]
    tail = f"; {q} quality {'win' if q == 1 else 'wins'} in 15 years, {v['top10_wins_15y']} over top-10 opponents"
    if v["entrenched"]:
        tail += f", which makes {obj} entrenched"
    return f"the ledger stands at {v['quality_wins']:+.1f}{inside}{tail}"


def _placement_phrase(v: dict, subj: str = "he", obj: str = "him") -> str:
    """The board's placement string ('score order #5; title cycle -> #2') read out with each rule glossed."""
    p = v["placement"]
    if p == "title holder":
        return f"{subj} holds the title and sits above the numbered board"
    if p.startswith("reserved"):
        return f"{subj} is reserved (vacated with injury, owed a title shot) and sits above the numbered board"
    steps = [s.strip() for s in p.split(";")]
    out = [steps[0].replace("score order", f"score order put {obj} at")]
    gloss = {"head-to-head": ("the head-to-head rule (the winner of the most recent meeting within three years moves directly above "
                              "the loser when ranked at most three places behind, six within a year)"),
             "title cycle": "the title-cycle rule (a losing title challenger is held at #4 or lower for 270 days, and the fighters behind move up)",
             "placement rules": "the placement rules (head-to-head and title cycle, solved together)"}
    for s in steps[1:]:
        m = re.match(r"(.+?) -> (#\d+)", s)
        if m:
            out.append(f"{gloss.get(m.group(1), m.group(1))} placed {obj} {m.group(2)}")
        else:
            out.append(s)
    return "; ".join(out)


def why_sentence(profile: dict) -> str:
    """Plain-language reading of the v1.0 score decomposition and placement."""
    v = profile["v10"]
    subj, obj, _ = pronouns(profile["division"])
    s = [_rating_phrase(v)]
    if v["inactivity_penalty"] > 0:
        s.append(f"after an inactivity penalty of {v['inactivity_penalty']:.0f} points for {v['days_since']} days without a bout")
    elif v["injury"]:
        s.append("with no inactivity penalty because the layoff is a documented injury")
    first = " ".join(s) + "; " + _ledger_phrase(v, obj)
    if v["form_penalty"] > 0:
        first += f"; form penalty {v['form_penalty']:.2f} for a {v['last5']} last five"
    else:
        first += f"; no form penalty ({v['last5']} last five)"
    first += "."
    if v["score"] is None or v["rating_term"] is None or v["ledger_term"] is None:
        return first
    second = (f" Score {v['score']:+.2f} = {v['rating_term']:+.2f} (rating term, 70% weight) {v['ledger_term']:+.2f} "
              f"(ledger term, 30% weight) -{v['form_penalty']:.2f} (form penalty); {_placement_phrase(v, subj, obj)}.")
    return first + second


def context_flags(profile: dict) -> list[str]:
    """Descriptive flags: age band with the published population rates, recent KO loss, long layoff, few bouts,
    then one line naming the checks that were not raised."""
    v, age = profile["v10"], profile["tape"].get("age")
    _, obj, _ = pronouns(profile["division"])
    flags, clear = [], []
    if age is None:
        flags.append("Age unknown (no date of birth on UFCStats), so no age band is shown.")
    else:
        band = next(b for b in AGE_BANDS if age < b[0])
        flags.append(f"Age band: {band[1]} (age {math.floor(age)}). On the board's own history (3,748 bouts between two board "
                     f"fighters, 2014 to 2026) the higher-scored fighter won {AGE_RATES} (EXP-2026-10-20-09). "
                     f"A population rate, not a forecast for {obj}.")
    ko_days = profile.get("last_ko_loss_days")
    if ko_days is not None and ko_days <= KO_WINDOW_DAYS:
        flags.append(f"Recent KO/TKO loss: {ko_days:.0f} days ago. The Association of Ringside Physicians consensus sets minimum "
                     "suspensions of 30 days after a head-strike TKO, 60 after a KO and 90 after a KO with loss of consciousness "
                     "(Neidecker et al. 2019, cited in EXP-2026-10-20-13); UFCStats does not record which applied.")
    else:
        clear.append(f"no KO/TKO loss in the last {KO_WINDOW_DAYS} days")
    if v["days_since"] > LAYOFF_FLAG_DAYS:
        flags.append(f"Layoff over 12 months: {v['days_since']} days since the last bout ({profile.get('last_bout') or v['last_fight']})"
                     + (", documented as an injury." if v["injury"] else "."))
    else:
        clear.append("last bout within 12 months")
    if v["ufc_bouts"] <= PROVISIONAL_MAX_BOUTS:
        rd = "" if v["rd"] is None else f" (deviation {v['rd']:.0f})"
        flags.append(f"Provisional: {v['ufc_bouts']} UFC {'bout' if v['ufc_bouts'] == 1 else 'bouts'}; the rating rests on little evidence{rd}.")
    else:
        clear.append(f"{v['ufc_bouts']} UFC bouts, more than the provisional limit of {PROVISIONAL_MAX_BOUTS}")
    if clear:
        flags.append("Not raised: " + "; ".join(clear) + ".")
    return flags


# ---------------------------------------------------------------------------
# charts (inline SVG, no script)

W, H, ML, MR, MT, MB = 640, 220, 44, 60, 12, 26


def _nice_step(span: float, max_ticks: int = 5) -> float:
    """The smallest round tick step that divides `span` into at most `max_ticks` intervals."""
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if span / step <= max_ticks:
            return step
    return 1000.0


def _svg_line(points: list[tuple[pd.Timestamp, float | None, str]], *, x0: pd.Timestamp, x1: pd.Timestamp,
              y0: float, y1: float, y_ticks: list[tuple[float, str]], invert: bool, end_text: str, aria: str) -> str:
    """A single-series line: hairline grid, 2px line, markers (or hover columns when dense), end label,
    year ticks on the x axis. Colours come from the page's CSS variables so dark mode follows."""
    span_x = max((x1 - x0).total_seconds(), 1.0)
    span_y = max(y1 - y0, 1e-9)
    pw, ph = W - ML - MR, H - MT - MB

    def px(x) -> float:
        return ML + (pd.Timestamp(x) - x0).total_seconds() / span_x * pw

    def py(y: float) -> float:
        frac = (y - y0) / span_y
        return MT + frac * ph if invert else H - MB - frac * ph

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px;height:auto;display:block" role="img" '
           f'aria-label="{html.escape(aria)}"><g font-size="11" fill="var(--muted)">']
    for yv, lab in y_ticks:
        yy = py(yv)
        out.append(f'<line x1="{ML}" x2="{W - MR}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--line)" stroke-width="1"/>'
                   f'<text x="{ML - 6}" y="{yy + 4:.1f}" text-anchor="end">{html.escape(lab)}</text>')
    years = list(range(x0.year + 1, x1.year + 1))
    step = max(1, math.ceil(len(years) / 8))
    ticks = [pd.Timestamp(year=y, month=1, day=1) for y in years[::step]]
    # the end labels ("Oct 2023") are about 48px wide and anchored outward; a year tick is centred, so it needs
    # about 80px of clearance from either end to avoid touching them
    for t in ticks:
        xx = px(t)
        if xx - px(x0) > 80 and px(x1) - xx > 80:
            out.append(f'<text x="{xx:.1f}" y="{H - 8}" text-anchor="middle">{t.year}</text>')
    for e, anchor in ((x0, "start"), (x1, "end")):
        out.append(f'<text x="{px(e):.1f}" y="{H - 8}" text-anchor="{anchor}">{e.strftime("%b %Y")}</text>')
    segs: list[list[tuple[float, float]]] = [[]]
    for x, y, _ in points:
        if y is None:
            if segs[-1]:
                segs.append([])
        else:
            segs[-1].append((px(x), py(y)))
    for seg in segs:
        if len(seg) >= 2:
            pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in seg)
            out.append(f'<polyline fill="none" stroke="var(--blue)" stroke-width="2" stroke-linejoin="round" '
                       f'stroke-linecap="round" points="{pts}"/>')
        elif len(seg) == 1:
            a, b = seg[0]
            out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="4" fill="var(--blue)"/>')
    have = [(px(x), py(y), tip) for x, y, tip in points if y is not None]
    if len(have) <= MARKER_LIMIT:
        for a, b, tip in have:
            out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="4" fill="var(--blue)" stroke="var(--surface)" stroke-width="2">'
                       f'<title>{html.escape(tip)}</title></circle>')
    else:
        xs = [a for a, _, _ in have]
        for i, (a, b, tip) in enumerate(have):
            left = (xs[i - 1] + a) / 2 if i else ML
            right = (xs[i + 1] + a) / 2 if i + 1 < len(xs) else W - MR
            out.append(f'<rect x="{left:.1f}" y="{MT}" width="{max(right - left, 0.5):.1f}" height="{ph}" fill="transparent">'
                       f'<title>{html.escape(tip)}</title></rect>')
    if have:
        a, b, _ = have[-1]
        if len(have) > MARKER_LIMIT:
            out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="4" fill="var(--blue)" stroke="var(--surface)" stroke-width="2"/>')
        out.append(f'<text x="{a + 8:.1f}" y="{b + 4:.1f}" fill="var(--ink2)">{html.escape(end_text)}</text>')
    out.append("</g></svg>")
    return "".join(out)


def rank_chart(profile: dict) -> str:
    """Board position by weekly v1.0 snapshot since Oct 2023; 0 (title holder) at the top, lower is better."""
    hist, dates = profile["rank_history"], profile["snapshot_dates"]
    if not hist or not dates:
        return "<p class='meta'>No board snapshots include this fighter.</p>"
    pos = {h["date"]: h for h in hist}
    worst = max(h["position"] for h in hist)
    step = _nice_step(max(worst, 10))
    top = max(10, math.ceil(worst / step) * step)
    ticks = [(0.0, "C")] + [(float(t), str(int(t))) for t in np.arange(step, top + step / 2, step)]
    pts = []
    for d in dates:
        h = pos.get(d)
        if h is None:
            pts.append((pd.Timestamp(d), None, ""))
        else:
            lab = "title holder" if h["position"] == 0 else f"#{h['position']}"
            pts.append((pd.Timestamp(d), float(h["position"]), f"{d}: {lab}, {h['division']}"))
    last = hist[-1]
    end = "C" if last["position"] == 0 else f"#{last['position']}"
    svg = _svg_line(pts, x0=pd.Timestamp(dates[0]), x1=pd.Timestamp(dates[-1]), y0=0.0, y1=float(top), y_ticks=ticks,
                    invert=True, end_text=end, aria=f"Board position of {profile['name']} by weekly snapshot")
    divs = []
    for h in hist:
        if not divs or divs[-1] != h["division"]:
            divs.append(h["division"])
    note = ""
    if len(divs) > 1:
        note = f" Listed at {', then '.join(html.escape(d) for d in divs)} over this period."
    missing = sum(1 for d in dates if d not in pos)
    if missing:
        note += f" Absent from {missing} of {len(dates)} snapshots (gaps in the line)."
    return svg + f"<p class='meta'>Position on the registered v1.0 board at each weekly snapshot (C = title holder or reserved, drawn at the top; lower is better).{note}</p>"


def rating_chart(profile: dict) -> str:
    """Predictive rating after each UFC bout (frozen performance-adjusted Elo)."""
    rows = profile["rating_history"]
    if not rows:
        return "<p class='meta'>No predictive rating history is recorded for this fighter.</p>"
    vals = [r["rating"] for r in rows]
    step = _nice_step(max(vals) - min(vals) + 1, max_ticks=5)
    step = max(step, 50)
    lo = math.floor(min(vals) / step) * step
    hi = math.ceil(max(vals) / step) * step
    if hi == lo:
        hi = lo + step
    ticks = [(float(t), f"{t:,.0f}") for t in np.arange(lo, hi + step / 2, step)]
    pts = [(pd.Timestamp(r["date"]), float(r["rating"]),
            f"{r['date']}: {r['rating']:,.0f}" + (f" ({r['result']} vs {r['opponent']})" if r.get("opponent") else ""))
           for r in rows]
    x0 = pd.Timestamp(rows[0]["date"])
    x1 = max(pd.Timestamp(profile["as_of"]), x0 + pd.Timedelta(days=30))
    svg = _svg_line(pts, x0=x0, x1=x1, y0=float(lo), y1=float(hi), y_ticks=ticks, invert=False,
                    end_text=f"{vals[-1]:,.0f}", aria=f"Predictive rating of {profile['name']} after each UFC bout")
    return svg + ("<p class='meta'>Rating after each UFC bout from the frozen predictive model (performance-adjusted Elo, "
                  "data/processed/elo_history.csv; a debut starts at 1,500). The resume rating's history is not stored, so this "
                  "is the predictive line, which is a different number from the resume rating in the header.</p>")


# ---------------------------------------------------------------------------
# pages

def _rank_line(profile: dict) -> str:
    """Both positions in one line: REAL v1.0 (registered) #k; v1.1 (shadow) #m."""
    v10, v11 = profile["v10"], profile["v11"]
    s = f"REAL v1.0 (registered) {v10['label']}"
    s += f"; v1.1 (shadow) {v11['label']}" if v11 else "; not on the v1.1 shadow board"
    return s


def _header(profile: dict) -> str:
    """Name, division, the two ranks, the weight band and deviation note, and the tale of the tape."""
    esc = html.escape
    v, t = profile["v10"], profile["tape"]
    _, _, poss = pronouns(profile["division"])
    bits = []
    if v["band"]:
        lo, hi = v["band"].split("-")
        same = " (the position does not depend on the weights)" if lo == hi else ""
        bits.append(f"Weight band {v['band']}: the 10th to 90th percentile of {poss} position across weight vectors drawn "
                    f"near the 70/30 weights{same}.")
    if v["rd"] is not None and v["rating"] is not None:
        bits.append(f"Rating {v['rating']:,.0f}, deviation {v['rd']:.0f}: measured from {v['ufc_bouts']} UFC "
                    f"{'bout' if v['ufc_bouts'] == 1 else 'bouts'}; a one-bout newcomer sits near {NEWCOMER_RD}.")
    if v["ufc_bouts"] <= PROVISIONAL_MAX_BOUTS:
        bits.append(f"<span class='flag'>Provisional: {v['ufc_bouts']} UFC {'bout' if v['ufc_bouts'] == 1 else 'bouts'}; "
                    "the rating rests on little evidence.</span>")
    if v["division_source"].startswith("override"):
        bits.append("Division set by a documented override (config/division_overrides.yaml).")
    age = "unknown" if t["age"] is None else f"{math.floor(t['age'])}" + (f" (born {t['dob']})" if t["dob"] else "")
    last = profile.get("last_bout") or v["last_fight"]
    tape = [f"Age {age}", f"Height {_height(t['height_in'])}", f"Reach {_reach(t['reach_in'])}",
            f"Stance {esc(t['stance']) if t['stance'] else 'unknown'}",
            f"{v['days_since']} days since last bout ({esc(last)})", f"Last five {esc(v['last5'])}",
            f"Streak {esc(v['streak'])}"]
    return (f"<h1>{esc(profile['name'])}</h1><p class='tag'>{esc(profile['division'])} · {esc(_rank_line(profile))}</p>"
            f"<p class='meta'>{esc(DISCLAIMER)}</p>"
            f"<p>{' '.join(bits)}</p>"
            f"<p class='meta'>{' · '.join(tape)}</p>")


def _num(x: float | None, fmt: str) -> str:
    """fmt applied to x, or n/a when it is missing."""
    return "n/a" if x is None else fmt.format(x)


def _why_section(profile: dict) -> str:
    """The plain sentence plus the score decomposition table (and the shadow board's own line)."""
    esc = html.escape
    v, v11 = profile["v10"], profile["v11"]
    rating_note = f"resume rating {_num(v['rating'], '{:,.0f}')}"
    if v["inactivity_penalty"] > 0:
        rating_note += f" (raw {_num(v['rating_raw'], '{:,.0f}')} less inactivity penalty {v['inactivity_penalty']:.0f})"
    rows = [("Score", _num(v["score"], "{:+.2f}"), "70% rating term + 30% ledger term - form penalty"),
            ("Rating term", _num(v["rating_term"], "{:+.2f}"), rating_note + ", scaled against the division's interdecile range"),
            ("Ledger term", _num(v["ledger_term"], "{:+.2f}"), f"quality ledger {v['quality_wins']:+.1f}: {esc(v['ledger_detail'])}"),
            ("Form penalty", f"{v['form_penalty']:.2f}", f"last five {esc(v['last5'])}"),
            ("Quality wins, 15 years", str(v["quality_wins_15y"]),
             f"{v['top10_wins_15y']} over top-10 opponents, {v['top15_wins_15y']} over top-15" + ("; entrenched" if v["entrenched"] else "")),
            ("Placement", esc(v["placement"]), "v1.0 (registered)")]
    if v11:
        rows.append(("Shadow board v1.1", esc(v11["label"]), f"score {_num(v11['score'], '{:+.2f}')}; {esc(v11['placement'])}"))
    body = "".join(f"<tr><td>{a}</td><td class='num'>{b}</td><td class='band'>{c}</td></tr>" for a, b, c in rows)
    subj = pronouns(profile["division"])[0]
    return (f"<h2>Why {subj} is ranked here</h2><p>{esc(why_sentence(profile))}</p>"
            f"<div class='scroll'><table><thead><tr><th>Term</th><th class='num'>Value</th><th>Detail</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
            "<p class='meta'>Rules, weights and worked examples: <a href='../methodology.html'>methodology</a>.</p>")


def _bouts_section(profile: dict) -> str:
    """The last ten bouts as a table with opponent links, official rank at the time and the model's probability."""
    esc = html.escape
    rows = []
    for b in profile["bouts"]:
        opp = esc(b["opponent"])
        if b.get("opponent_slug"):
            opp = f"<a href='{esc(b['opponent_slug'])}.html'>{opp}</a>"
        rd = "" if b["round"] is None else f"{b['round']}" + (f" ({b['time']})" if b.get("time") else "")
        p = "" if b["p"] is None else f"{b['p']:.0%}"
        title = " <span class='band'>(title)</span>" if b.get("title_fight") else ""
        cls = {"W": "up", "L": "down"}.get(b["result"], "band")
        rows.append(f"<tr><td class='nw'>{esc(b['date'])}</td><td>{esc(b['event'])}{title}</td><td>{opp}</td><td class='nw'>{esc(b['opp_rank'])}</td>"
                    f"<td class='{cls}'>{esc(b['result'])}</td><td>{esc(b['method'])}</td><td class='nw'>{rd}</td><td class='num'>{p}</td></tr>")
    if not rows:
        return "<h2>Last ten bouts</h2><p class='meta'>No UFC bouts in the data.</p>"
    heading = "Last ten bouts" if len(rows) >= LAST_BOUTS else f"All {len(rows)} UFC {'bout' if len(rows) == 1 else 'bouts'}"
    return (f"<h2>{heading}</h2><div class='scroll'><table><thead><tr><th>Date</th><th>Event</th><th>Opponent</th>"
            "<th>Opp. official rank</th><th>Result</th><th>Method</th><th>Round</th><th class='num nw'>Model p</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            "<p class='meta'>Opp. official rank = the UFC media-panel rank of the opponent on the date (C champion, #1 to #15, unranked; "
            f"n/a before Feb 2013 or where no official board existed). Model p = the predictive model's pre-fight win chance for {pronouns(profile['division'])[1]} "
            "(frozen performance-adjusted Elo; bouts before 2020 were in its tuning sample). Linked opponents have a profile.</p>")


def _stat_value(profile: dict, col: str, fmt: str | None) -> str:
    """One statistic cell: the formatted value, the KO-loss recency gloss, or the style with its two markers."""
    esc = html.escape
    if col == "style":
        td, ctrl = profile.get("td_rate"), profile["stats"].get("ctrl_share", {}).get("value")
        gloss = []
        if td is not None:
            gloss.append(f"{td:.1f} takedown attempts per 15 min")
        if ctrl is not None:
            gloss.append(f"{ctrl:.0%} control")
        return esc(profile.get("style", "unknown")) + (f" <span class='band'>({'; '.join(gloss)})</span>" if gloss else "")
    s = profile["stats"].get(col, {})
    val = s.get("value")
    if val is None:
        return "<span class='band'>n/a</span>"
    if col == "ko_losses":
        text = f"{val:.0f}"
        days = profile.get("last_ko_loss_days")
        if val > 0 and days is not None:
            last = pd.Timestamp(profile["as_of"]) + pd.Timedelta(days=1) - pd.Timedelta(days=int(days))
            text += f" <span class='band'>(last {last.date()}, {days:,.0f} days ago)</span>"
        return text
    return fmt.format(val)


def _stats_section(profile: dict) -> str:
    """Career statistics grouped with division percentiles, then the two charts."""
    esc = html.escape
    div, n = profile["division"], profile["v10"]["division_size"]
    parts = [f"<h2>Career statistics</h2><p class='meta'>Through {esc(profile['as_of'])}, UFC bouts only. Percentile = share of the "
             f"{n} board fighters at {esc(div)} at or below this value; high is a position in the division, not a verdict.</p>"]
    rows = []
    for heading, items in STAT_GROUPS:
        rows.append(f"<tr><th class='grp' colspan='3'>{esc(heading)}</th></tr>")
        for col, label, fmt in items:
            pct = profile["stats"].get(col, {}).get("pct") if col != "style" else None
            pct_s = f"<span class='band'>({_ordinal(pct)} percentile at {esc(div)})</span>" if pct is not None else ""
            rows.append(f"<tr><td>{esc(label)}</td><td class='num'>{_stat_value(profile, col, fmt)}</td><td>{pct_s}</td></tr>")
    parts.append(f"<div class='scroll'><table class='stats'><tbody>{''.join(rows)}</tbody></table></div>")
    parts.append(f"<h3>Board position since Oct 2023</h3>{rank_chart(profile)}")
    parts.append(f"<h3>Predictive rating by bout</h3>{rating_chart(profile)}")
    return "".join(parts)


def _flags_section(profile: dict) -> str:
    """The descriptive context flags as a list under their own disclaimer."""
    items = "".join(f"<li>{html.escape(f)}</li>" for f in context_flags(profile))
    obj = pronouns(profile["division"])[1]
    return (f"<h2>Context flags</h2><p class='meta'>Descriptive only. Each line is a population fact about fighters like {obj}, "
            f"not a forecast for {obj}; the register entries hold the measurements.</p>"
            f"<ul class='fav'>{items}</ul>")


def render(profile: dict) -> str:
    """The full HTML page for one profile."""
    esc = html.escape
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(profile['name'])}</title><style>{publish.CSS}{EXTRA_CSS}</style></head><body>
<p class="meta"><a href="../index.html">Back to the boards</a> · <a href="index.html">All fighter profiles</a></p>
{_header(profile)}
{_why_section(profile)}
{_bouts_section(profile)}
{_stats_section(profile)}
{_flags_section(profile)}
{publish.footer(profile['as_of'])}
</body></html>"""
    return page.replace(EM_DASH, "-")


def render_index(profiles: list[dict], as_of: str) -> str:
    """Alphabetical list by surname, grouped by division, with both ranks and a link to every page."""
    esc = html.escape

    def key(p: dict) -> tuple:
        """Sort by surname: the last word after dropping a parenthetical suffix and a generational one (Jr., III)."""
        base = re.sub(r"\s*\(.*\)\s*$", "", p["name"])
        words = [w for w in base.split() if re.sub(r"[^a-z]", "", w.lower()) not in {"jr", "sr", "ii", "iii", "iv"}]
        return (words[-1].lower() if words else base.lower(), base.lower())

    def short(p: dict) -> str:
        v11 = p["v11"]
        return f"v1.0 {p['v10']['label']} · v1.1 {v11['label'] if v11 else 'not listed'}"

    by_div: dict[str, list[dict]] = {}
    for p in profiles:
        by_div.setdefault(p["division"], []).append(p)
    order = [d for d in RANKED_DIVISIONS if d in by_div] + sorted(d for d in by_div if d not in RANKED_DIVISIONS)
    parts = []
    for div in order:
        items = "".join(f"<li><a href='{esc(p['slug'])}.html'>{esc(p['name'])}</a> <span class='band'>{esc(short(p))}</span></li>"
                        for p in sorted(by_div[div], key=key))
        parts.append(f"<h2>{esc(div)}</h2><ul class='fav cols'>{items}</ul>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fighter profiles</title><style>{publish.CSS}{EXTRA_CSS}</style></head><body>
<p class="meta"><a href="../index.html">Back to the boards</a></p>
<h1>Fighter profiles</h1>
<p class="meta">{esc(DISCLAIMER)}</p>
<p class="meta">{len(profiles)} fighters on the registered board, grouped by division and sorted by surname. v1.0 = the registered
REAL board, v1.1 = the shadow board published beside it; title holders and reserved spots are named, contenders carry their
position. Data through {esc(as_of)}.</p>
{''.join(parts)}
{publish.footer(as_of)}
</body></html>""".replace(EM_DASH, "-")


def main() -> None:
    """Write docs/fighters/<slug>.html for every board fighter and docs/fighters/index.html."""
    src = load_sources()
    profiles = build_profiles(src)
    PAGES.mkdir(parents=True, exist_ok=True)
    collisions = [(n, s) for n, s in unique_slugs(src["board"]["fighter"]).items() if s != slug(n)]
    for n, s in collisions:
        print(f"note: {n!r} shares a slug with another board name and is written as {s}.html")
    total = 0
    for p in profiles:
        text = render(p)
        (PAGES / f"{p['slug']}.html").write_text(text)
        total += len(text.encode())
    as_of = str(src["as_of"].date())
    (PAGES / "index.html").write_text(render_index(profiles, as_of))
    print(f"docs/fighters: {len(profiles)} profiles written ({total / 1024:.0f} KB; data through {as_of})")


if __name__ == "__main__":
    main()
