"""
picks.py - Pre-event picks from the frozen prediction model, locked before each card and graded after it.

What it does, in order:
  1. fetch     pull the upcoming UFC schedule (names, dates, weight classes) from ESPN's public feed
               and save the raw JSON to data/external/espn_upcoming.json. If the feed cannot be
               reached (for example from a sandbox), the saved copy is used and nothing else changes.
               validate_feed() checks the payload has the structure parse_upcoming() reads; a payload
               that fails the check is reported in picks_summary.json (feed_status) and nothing is
               locked that run, while grading and the summary still run.
  2. lock      for every scheduled bout inside the horizon that is not yet in the ledger, write one
               row to predictions/picks.csv with the frozen performance-adjusted Elo probability,
               the results-only Elo probability and the REAL board probability, the pick, the
               confidence band, a provisional flag, and the UTC time the pick was made. Rows are
               never edited afterwards: the git history of the file is the timestamp proof.
               From no_pick_since (config/picks.yaml), a probability inside the no-pick band around
               0.5 is recorded as pick "none" with band "no pick"; the shadow pick follows the same
               rule on its own probability.
  3. grade     match pending picks to results in data/processed/bouts.csv (UFCStats) and record
               correct / incorrect / void with log loss and Brier score. A row with pick "none" is
               recorded as "no pick": not correct, not incorrect, not void, and outside the accuracy,
               log loss and Brier figures.
  4. summarize write outputs/picks_summary.json: the running record, calibration, per-event results,
               the paired comparison with the two baselines on the same graded bouts, the no-pick
               count and the feed status. cumulative_chart_svg() draws the running record to
               outputs/picks_cumulative.svg.

The predictive model is the specification the grid selected on 2010-2019 (outputs/backtest_report.json,
tuned_params), frozen with REAL v1.0 on Oct 1, 2026. Ratings are recomputed from the full bout history
on every run, so a fighter's rating reflects every bout UFCStats has recorded through data_through.
"""
from __future__ import annotations

import html
import json
import math
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.compare import norm
from mmalab.elo import EloParams, run_elo

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
EXT = ROOT / "data" / "external"
OUT = ROOT / "outputs"
PRED = ROOT / "predictions"
CFG = ROOT / "config"

LEDGER = PRED / "picks.csv"
RAW = EXT / "espn_upcoming.json"
UNMATCHED = PRED / "unmatched_names.csv"

COLUMNS = ["pick_id", "predicted_at_utc", "data_through", "model", "freeze_commit",
           "event_id", "event", "event_date", "division", "rounds",
           "fighter_a", "fighter_b", "espn_name_a", "espn_name_b", "matched_a", "matched_b",
           "ufc_bouts_a", "ufc_bouts_b", "rating_a", "rating_b", "p_a", "pick", "p_pick", "confidence",
           "provisional", "p_a_classic", "pick_classic", "p_a_real", "pick_real",
           "status", "winner", "method", "result_date", "bout_url", "correct", "log_loss", "brier", "graded_at_utc", "note",
           "p_a_v11", "pick_v11", "v11_locked_at_utc", "first_listed_matches"]


def _cfg() -> dict:
    return yaml.safe_load((CFG / "picks.yaml").read_text())


def _aliases() -> dict:
    p = CFG / "name_aliases.yaml"
    raw = yaml.safe_load(p.read_text()) if p.exists() else None
    return {norm(k): norm(v) for k, v in (raw or {}).items()}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- 1. fetch ----------

def fetch(days: int) -> dict | None:
    cfg = _cfg()
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=days)
    url = f"{cfg['source']}?dates={start:%Y%m%d}-{end:%Y%m%d}"
    req = urllib.request.Request(url, headers={"User-Agent": "real-fighter-rankings/1.0 (research; github.com/braytonsmith-dev/real-fighter-rankings)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - any network failure means "use the saved copy"
        print(f"picks: schedule feed not reachable ({type(e).__name__}); using the saved copy if there is one")
        return json.loads(RAW.read_text()) if RAW.exists() else None
    if validate_feed(data):
        print("picks: the live feed failed the schema check; the saved copy was left as it was")
        return data
    EXT.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps({"fetched_at_utc": _now(), "url": url, "events": data.get("events", [])}, indent=1))
    return data


MAX_FEED_PROBLEMS = 30


def validate_feed(payload: object) -> list[str]:
    """Check that an ESPN scoreboard payload has the structure parse_upcoming() reads and return the problems found
    (an empty list means the feed looks right). Container types are checked everywhere the parser touches them;
    the per-bout fields (two named athletes, weight class, scheduled rounds) are only required of bouts the parser
    would lock, that is scheduled bouts with exactly two competitors, so a TBA slot or a finished bout never
    blocks a run. The list is capped at MAX_FEED_PROBLEMS entries."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["payload is not a JSON object"]
    events = payload.get("events")
    if not isinstance(events, list):
        return ["'events' is missing or not a list"]
    for i, ev in enumerate(events):
        tag = f"events[{i}]"
        if not isinstance(ev, dict):
            problems.append(f"{tag}: not an object")
            continue
        if not isinstance(ev.get("id"), (str, int)):
            problems.append(f"{tag}.id: missing")
        if not isinstance(ev.get("name"), str) or not ev["name"].strip():
            problems.append(f"{tag}.name: missing")
        when = ev.get("date")
        if not isinstance(when, str) or len(when) < 10:
            problems.append(f"{tag}.date: missing or not an ISO date")
        else:
            try:
                datetime.strptime(when[:10], "%Y-%m-%d")
            except ValueError:
                problems.append(f"{tag}.date: {when!r} is not an ISO date")
        comps = ev.get("competitions")
        if not isinstance(comps, list):
            problems.append(f"{tag}.competitions: missing or not a list")
            continue
        for j, comp in enumerate(comps):
            ctag = f"{tag}.competitions[{j}]"
            if not isinstance(comp, dict):
                problems.append(f"{ctag}: not an object")
                continue
            if not isinstance(comp.get("id"), (str, int)):
                problems.append(f"{ctag}.id: missing")
            status = comp.get("status", {})
            st = status.get("type", {}) if isinstance(status, dict) else None
            if not isinstance(st, dict):
                problems.append(f"{ctag}.status.type: not an object")
                st = {}
            competitors = comp.get("competitors")
            if not isinstance(competitors, list):
                problems.append(f"{ctag}.competitors: missing or not a list")
                continue
            scheduled = not st.get("completed") and st.get("state") in (None, "pre") and len(competitors) == 2
            for k, c in enumerate(competitors):
                ptag = f"{ctag}.competitors[{k}]"
                if not isinstance(c, dict):
                    problems.append(f"{ptag}: not an object")
                    continue
                ath = c.get("athlete")
                if not isinstance(ath, dict):
                    if scheduled:
                        problems.append(f"{ptag}.athlete: missing")
                    continue
                name = ath.get("displayName") or ath.get("fullName")
                if scheduled and not (isinstance(name, str) and name.strip()):
                    problems.append(f"{ptag}.athlete: no displayName or fullName")
            if scheduled:
                wt = comp.get("type")
                if not isinstance(wt, dict) or not (wt.get("abbreviation") or wt.get("text")):
                    problems.append(f"{ctag}.type: no weight class (abbreviation or text)")
                fmt = comp.get("format", {})
                reg = fmt.get("regulation", {}) if isinstance(fmt, dict) else None
                periods = reg.get("periods") if isinstance(reg, dict) else None
                if not isinstance(periods, int) or periods <= 0:
                    problems.append(f"{ctag}.format.regulation.periods: missing")
    if len(problems) > MAX_FEED_PROBLEMS:
        extra = len(problems) - MAX_FEED_PROBLEMS
        problems = problems[:MAX_FEED_PROBLEMS] + [f"... and {extra} more"]
    return problems


WEIGHT_FIX = {"W ": "Women's "}


def _division(text: str) -> str:
    t = (text or "").strip()
    for k, v in WEIGHT_FIX.items():
        if t.startswith(k):
            t = v + t[len(k):]
    return t or "Unknown"


def parse_upcoming(data: dict, data_through: pd.Timestamp) -> pd.DataFrame:
    """One row per scheduled bout on a UFC card after data_through."""
    cfg = _cfg()
    rows = []
    for ev in data.get("events", []):
        name = ev.get("name", "")
        if any(x.lower() in name.lower() for x in cfg["exclude_events"]) or "UFC" not in name.upper():
            continue
        ev_date = pd.Timestamp(ev["date"][:10])
        if ev_date <= data_through:
            continue
        for comp in ev.get("competitions", []):
            st = comp.get("status", {}).get("type", {})
            if st.get("completed") or st.get("state") not in (None, "pre"):
                continue
            comps = sorted(comp.get("competitors", []), key=lambda c: c.get("order", 99))
            if len(comps) != 2:
                continue
            names = [c.get("athlete", {}).get("displayName") or c.get("athlete", {}).get("fullName") for c in comps]
            if not all(names) or any(n.strip().upper() in ("TBA", "TBD") or "OPPONENT" in n.upper() for n in names):
                continue
            rows.append({
                "event_id": str(ev.get("id")), "event": name, "event_date": ev_date.date(),
                "competition_id": str(comp.get("id")),
                "division": _division(comp.get("type", {}).get("abbreviation") or comp.get("type", {}).get("text")),
                "rounds": int(comp.get("format", {}).get("regulation", {}).get("periods") or 3),
                "espn_name_a": names[0], "espn_name_b": names[1],
                "athlete_a": str(comps[0].get("id")), "athlete_b": str(comps[1].get("id")),
            })
    return pd.DataFrame(rows)


# ---------- 2. lock ----------

def _roster(bouts: pd.DataFrame) -> dict:
    counts = pd.concat([bouts["fighter_a"], bouts["fighter_b"]]).value_counts()
    return {norm(n): (n, int(c)) for n, c in counts.items()}


def _match(espn_name: str, roster: dict, aliases: dict) -> tuple[str | None, int]:
    k = aliases.get(norm(espn_name), norm(espn_name))
    if k in roster:
        return roster[k]
    return None, 0


def _ratings() -> tuple[dict, dict]:
    rep = json.loads((OUT / "backtest_report.json").read_text())
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    out = {}
    for key in ("tuned_params", "classic_tuned_params"):
        _, hist = run_elo(bouts, EloParams(**rep[key]))
        out[key] = hist.groupby("fighter").tail(1).set_index("fighter")["rating"].to_dict()
    return out["tuned_params"], out["classic_tuned_params"]


def _real_scores() -> dict:
    p = OUT / "composite_rankings_full.csv"
    if not p.exists():
        return {}
    b = pd.read_csv(p)
    return {r.fighter: (r.division, float(r.score)) for r in b.itertuples()}


class Shadow:
    """Shadow v1.1 (outputs/shadow_v11.json): walk-forward-tuned Elo with a red-corner term plus a logistic layer
    on age, layoff, experience, height and five-round bouts. Reported next to v1.0, never substituted for it."""

    def __init__(self):
        self.ok = False
        path = OUT / "shadow_v11.json"
        if not path.exists():
            return
        self.spec = json.loads(path.read_text())
        bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
        rated, hist = run_elo(bouts, EloParams(**self.spec["elo_params"]))
        self.rating = hist.groupby("fighter").tail(1).set_index("fighter")["rating"].to_dict()
        last = pd.concat([rated[["date", "fighter_a"]].rename(columns={"fighter_a": "fighter"}),
                          rated[["date", "fighter_b"]].rename(columns={"fighter_b": "fighter"})]).groupby("fighter")["date"].max()
        self.last_date = last.to_dict()
        self.bouts_n = pd.concat([rated["fighter_a"], rated["fighter_b"]]).value_counts().to_dict()
        fighters = pd.read_csv(PROC / "fighters.csv")
        self.dob = pd.to_datetime(fighters.set_index("fighter")["dob"], errors="coerce").to_dict()
        self.height = fighters.set_index("fighter")["height_in"].to_dict()
        self.ok = True

    def prob(self, a: str, b: str, event_date: pd.Timestamp, rounds: int) -> float:
        lg, corner = self.spec["logistic"], self.spec["elo_params"]["corner_adv"]
        ra, rb = self.rating.get(a, 1500.0), self.rating.get(b, 1500.0)

        def age(n):
            d = self.dob.get(n)
            return (event_date - d).days / 365.25 if d is not None and not pd.isna(d) else None

        def lay(n):
            d = self.last_date.get(n)
            return float((event_date - d).days) if d is not None else 365.0

        aa, ab = age(a), age(b)
        ea, eb = float(self.bouts_n.get(a, 0)), float(self.bouts_n.get(b, 0))
        ha, hb = self.height.get(a), self.height.get(b)
        x = {"elo_diff": (ra + corner - rb) / 400.0,
             "age_diff": (aa - ab) if aa is not None and ab is not None else 0.0,
             "old_diff": ((max(aa, 33) - 33) if aa is not None else 0.0) - ((max(ab, 33) - 33) if ab is not None else 0.0),
             "layoff_diff": math.log1p(lay(a)) - math.log1p(lay(b)),
             "debut_diff": float(ea == 0) - float(eb == 0), "exp_diff": math.log1p(ea) - math.log1p(eb),
             "height_diff": (ha - hb) if ha is not None and hb is not None and not (pd.isna(ha) or pd.isna(hb)) else 0.0,
             "five_round": 1.0 if int(rounds) >= 5 else 0.0}
        x["elo_x_five"] = x["elo_diff"] * x["five_round"]
        z = lg["weights"][0] + sum(w * (x[f] - m) / sd for f, w, m, sd in zip(lg["features"], lg["weights"][1:], lg["mean"], lg["std"]))
        return 1.0 / (1.0 + math.exp(-z))


def _p(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def _band(p_pick: float, bands: list[float]) -> str:
    for lo, hi in zip(bands, bands[1:]):
        if lo <= p_pick < hi or (hi == bands[-1] and p_pick >= lo):
            return f"{lo:.0%}-{hi:.0%}" if hi < 1 else f"{lo:.0%}+"
    return "n/a"


NO_PICK = "none"          # the pick column of a row inside the no-pick band
NO_PICK_BAND = "no pick"  # its confidence band, and the status it is graded with


def no_pick_band_for(cfg: dict, on: date) -> float | None:
    """The no-pick half-width in force for a row locked on the given UTC date, or None when the rule does not
    apply (no band configured, or the date is before no_pick_since). Rows locked earlier keep their picks."""
    band, since = cfg.get("no_pick_band"), cfg.get("no_pick_since")
    if not band or since is None or on < pd.Timestamp(since).date():
        return None
    return float(band)


def choose_pick(p_a: float, fighter_a: str, fighter_b: str, band: float | None) -> str:
    """The pick for a probability that fighter_a wins: fighter_a at 0.5 and above, fighter_b below, or NO_PICK when
    |p_a - 0.5| is strictly inside the band. The comparison is made at six decimals so a probability stored to
    four decimals (0.5200 with a 0.02 band) sits on the edge and still produces a pick."""
    if band is not None and round(abs(p_a - 0.5), 6) < band:
        return NO_PICK
    return fighter_a if p_a >= 0.5 else fighter_b


def load_ledger() -> pd.DataFrame:
    if LEDGER.exists():
        df = pd.read_csv(LEDGER, dtype=str, keep_default_na=False)
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = ""
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)


def _shadow_fill(ledger: pd.DataFrame, data_through: pd.Timestamp) -> pd.DataFrame:
    """A pending v1.0 pick locked before the shadow model existed gets a shadow pick of its own, with its own
    timestamp, as long as the bout has not happened. The v1.0 columns are untouched. The no-pick band applies
    to the shadow pick when the fill happens on or after no_pick_since."""
    if ledger.empty:
        return ledger
    todo = ledger[(ledger["status"] == "pending") & (ledger["p_a_v11"] == "") & (pd.to_datetime(ledger["event_date"]) > data_through)]
    if todo.empty:
        return ledger
    shadow = Shadow()
    if not shadow.ok:
        return ledger
    band = no_pick_band_for(_cfg(), datetime.now(timezone.utc).date())
    for i, r in todo.iterrows():
        p11 = shadow.prob(r["fighter_a"], r["fighter_b"], pd.Timestamp(r["event_date"]), int(r["rounds"] or 3))
        ledger.loc[i, ["p_a_v11", "pick_v11", "v11_locked_at_utc"]] = [f"{p11:.4f}", choose_pick(round(p11, 4), r["fighter_a"], r["fighter_b"], band), _now()]
    PRED.mkdir(exist_ok=True)
    ledger.to_csv(LEDGER, index=False)
    print(f"picks: shadow v1.1 picks added to {len(todo)} pending row(s)")
    return ledger


def lock(upcoming: pd.DataFrame, data_through: pd.Timestamp) -> pd.DataFrame:
    cfg = _cfg()
    ledger = load_ledger()
    ledger = _shadow_fill(ledger, data_through)
    if upcoming.empty:
        return ledger
    horizon = pd.Timestamp(datetime.now(timezone.utc).date()) + pd.Timedelta(days=cfg["horizon_days"])
    up = upcoming[pd.to_datetime(upcoming["event_date"]) <= horizon].copy()
    up["pick_id"] = up["event_id"] + ":" + up["competition_id"]
    new = up[~up["pick_id"].isin(set(ledger["pick_id"]))]
    if new.empty:
        return ledger
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    roster, aliases = _roster(bouts), _aliases()
    tuned, classic = _ratings()
    real = _real_scores()
    shadow = Shadow()
    rep = json.loads((OUT / "backtest_report.json").read_text())
    freeze = (OUT / "freeze_hash.txt").read_text().split()[0] if (OUT / "freeze_hash.txt").exists() else ""
    slope = 1.36   # PREREGISTRATION.md section 5
    band = no_pick_band_for(cfg, datetime.now(timezone.utc).date())
    rows, misses = [], []
    for r in new.itertuples():
        na, ca = _match(r.espn_name_a, roster, aliases)
        nb, cb = _match(r.espn_name_b, roster, aliases)
        for espn, hit in ((r.espn_name_a, na), (r.espn_name_b, nb)):
            if hit is None:
                misses.append({"event": r.event, "event_date": r.event_date, "espn_name": espn, "seen_at_utc": _now()})
        fa, fb = na or r.espn_name_a, nb or r.espn_name_b
        ra, rb = tuned.get(fa, 1500.0), tuned.get(fb, 1500.0)
        pa = _p(ra, rb)
        pick = choose_pick(round(pa, 4), fa, fb, band)   # the rule reads the probability as the ledger stores it
        p_pick = max(pa, 1 - pa)
        pac = _p(classic.get(fa, 1500.0), classic.get(fb, 1500.0))
        sa, sb = real.get(fa), real.get(fb)
        par = ""
        pick_real = ""
        if sa and sb and sa[0] == sb[0]:
            par = 1.0 / (1.0 + math.exp(-slope * (sa[1] - sb[1])))
            pick_real = fa if par >= 0.5 else fb
        p11 = shadow.prob(fa, fb, pd.Timestamp(r.event_date), r.rounds) if shadow.ok else ""
        rows.append({
            "p_a_v11": round(p11, 4) if p11 != "" else "", "pick_v11": choose_pick(round(p11, 4), fa, fb, band) if p11 != "" else "",
            "v11_locked_at_utc": _now() if p11 != "" else "", "first_listed_matches": "",
            "pick_id": r.pick_id, "predicted_at_utc": _now(), "data_through": str(data_through.date()),
            "model": "performance-adjusted Elo v1.0 (tuned_params)", "freeze_commit": freeze,
            "event_id": r.event_id, "event": r.event, "event_date": str(r.event_date), "division": r.division, "rounds": r.rounds,
            "fighter_a": fa, "fighter_b": fb, "espn_name_a": r.espn_name_a, "espn_name_b": r.espn_name_b,
            "matched_a": bool(na), "matched_b": bool(nb), "ufc_bouts_a": ca, "ufc_bouts_b": cb,
            "rating_a": round(ra, 1), "rating_b": round(rb, 1), "p_a": round(pa, 4), "pick": pick, "p_pick": round(p_pick, 4),
            "confidence": NO_PICK_BAND if pick == NO_PICK else _band(p_pick, cfg["confidence_bands"]),
            "provisional": bool(min(ca, cb) <= cfg["provisional_max_bouts"]),
            "p_a_classic": round(pac, 4), "pick_classic": fa if pac >= 0.5 else fb,
            "p_a_real": round(par, 4) if par != "" else "", "pick_real": pick_real,
            "status": "pending", "winner": "", "method": "", "result_date": "", "bout_url": "",
            "correct": "", "log_loss": "", "brier": "", "graded_at_utc": "",
            "note": "" if (na and nb) else "name not in UFCStats history; treated as a debut at 1500",
        })
    ledger = pd.concat([ledger, pd.DataFrame(rows, columns=COLUMNS).astype(str)], ignore_index=True)
    PRED.mkdir(exist_ok=True)
    ledger.to_csv(LEDGER, index=False)
    if misses:
        old = pd.read_csv(UNMATCHED, dtype=str) if UNMATCHED.exists() else pd.DataFrame()
        pd.concat([old, pd.DataFrame(misses)], ignore_index=True).drop_duplicates(["event", "espn_name"]).to_csv(UNMATCHED, index=False)
    print(f"picks: locked {len(rows)} new pick(s); ledger now {len(ledger)} rows")
    return ledger


# ---------- 3. grade ----------

def grade(ledger: pd.DataFrame, data_through: pd.Timestamp) -> pd.DataFrame:
    cfg = _cfg()
    if ledger.empty:
        return ledger
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    bouts["key"] = [frozenset((norm(a), norm(b))) for a, b in zip(bouts["fighter_a"], bouts["fighter_b"])]
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    win = pd.Timedelta(days=cfg["match_window_days"])
    for i, r in ledger[ledger["status"] == "pending"].iterrows():
        ev_date = pd.Timestamp(r["event_date"])
        if ev_date - win > data_through:      # feed dates are UTC, so a Saturday US card can carry Sunday's date
            continue
        key = frozenset((norm(r["fighter_a"]), norm(r["fighter_b"])))
        m = bouts[(bouts["key"] == key) & (bouts["date"].between(ev_date - win, ev_date + win))]
        if m.empty:
            if today > ev_date + pd.Timedelta(days=cfg["void_after_days"]):
                ledger.loc[i, ["status", "note", "graded_at_utc"]] = ["void", "no matching result within the window (bout fell through, or a name did not match)", _now()]
            continue
        x = m.iloc[0]
        res = x["result_a"]
        ledger.loc[i, "first_listed_matches"] = str(norm(x["fighter_a"]) == norm(r["fighter_a"]))
        ledger.loc[i, ["result_date", "bout_url", "method", "graded_at_utc"]] = [str(x["date"].date()), x["bout_url"], x["method"], _now()]
        draw = bool(pd.isna(res) or res == 0.5)
        if r["pick"] == NO_PICK:
            # abstained at lock time: the result is recorded for the shadow pick, nothing is scored for v1.0
            winner = "" if draw else (x["fighter_a"] if res == 1.0 else x["fighter_b"])
            note = "no pick: p_a inside the no-pick band at lock time" + ("; draw or no contest" if draw else "")
            ledger.loc[i, ["status", "winner", "note"]] = [NO_PICK_BAND, winner, f"{r['note']}; {note}" if r["note"] else note]
            continue
        if draw:
            ledger.loc[i, ["status", "winner", "note"]] = ["void", "", "draw or no contest: not scored"]
            continue
        winner = (x["fighter_a"] if res == 1.0 else x["fighter_b"])
        y = 1.0 if (norm(winner) == norm(r["fighter_a"])) else 0.0
        p = float(r["p_a"])
        pc = min(max(p, 1e-6), 1 - 1e-6)
        ledger.loc[i, ["status", "winner", "correct", "log_loss", "brier"]] = [
            "correct" if norm(r["pick"]) == norm(winner) else "incorrect", winner,
            str(norm(r["pick"]) == norm(winner)),
            f"{-(y * math.log(pc) + (1 - y) * math.log(1 - pc)):.4f}", f"{(p - y) ** 2:.4f}"]
    ledger.to_csv(LEDGER, index=False)
    return ledger


# ---------- 4. summarize ----------

def _wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 3), round(c + h, 3)]


def summarize(ledger: pd.DataFrame, feed_status: dict | None = None) -> dict:
    """Write outputs/picks_summary.json and return it. Graded means correct or incorrect; a "no pick" row is counted
    on its own (no_pick) and never enters accuracy, log loss, Brier or the calibration table. feed_status, when
    given, is recorded as the result of the schedule feed's schema check for this run."""
    g = ledger[ledger["status"].isin(["correct", "incorrect"])].copy()
    pending = ledger[ledger["status"] == "pending"]
    no_pick = ledger[ledger["status"] == NO_PICK_BAND]
    out = {"updated_utc": _now(), "graded": int(len(g)), "pending": int(len(pending)),
           "void": int((ledger["status"] == "void").sum()), "no_pick": int(len(no_pick)),
           "protocol": "PREREGISTRATION.md, appendix A"}
    if feed_status is not None:
        out["feed_status"] = feed_status
    if len(g):
        g["correct_b"] = g["correct"] == "True"
        g["ll"] = g["log_loss"].astype(float)
        g["br"] = g["brier"].astype(float)
        g["y_a"] = (g["winner"].map(norm) == g["fighter_a"].map(norm)).astype(float)
        k = int(g["correct_b"].sum())
        out["record"] = {"correct": k, "incorrect": int(len(g) - k), "accuracy": round(k / len(g), 3),
                         "accuracy_wilson95": _wilson(k, len(g)), "log_loss": round(float(g["ll"].mean()), 4),
                         "brier": round(float(g["br"].mean()), 4), "coin_flip_log_loss": 0.6931}
        # baselines on exactly the same graded bouts; a shadow "none" is an abstention and is counted, not scored
        base = {}
        for label, col_pick, col_p in (("results_only_elo", "pick_classic", "p_a_classic"), ("real_board", "pick_real", "p_a_real"),
                                       ("shadow_v11", "pick_v11", "p_a_v11")):
            h = g[~g[col_pick].isin(["", NO_PICK])]
            if len(h):
                p = h[col_p].astype(float).clip(1e-6, 1 - 1e-6)
                y = h["y_a"]
                base[label] = {"n": int(len(h)), "accuracy": round(float((h[col_pick].map(norm) == h["winner"].map(norm)).mean()), 3),
                               "log_loss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4),
                               "model_accuracy_same_bouts": round(float(h["correct_b"].mean()), 3),
                               "model_log_loss_same_bouts": round(float(h["ll"].mean()), 4),
                               "no_pick": int((g[col_pick] == NO_PICK).sum())}
        out["baselines_same_bouts"] = base
        out["by_confidence"] = [{"band": b, "n": int(len(x)), "accuracy": round(float(x["correct_b"].mean()), 3),
                                 "mean_p_pick": round(float(x["p_pick"].astype(float).mean()), 3)}
                                for b, x in g.groupby("confidence", sort=True)]
        flm = g[g["first_listed_matches"] != ""]
        if len(flm):
            out["feed_order_matches_ufcstats_first_listed"] = round(float((flm["first_listed_matches"] == "True").mean()), 3)
        out["provisional"] = {"n": int((g["provisional"] == "True").sum()),
                              "accuracy": round(float(g.loc[g["provisional"] == "True", "correct_b"].mean()), 3) if (g["provisional"] == "True").any() else None}
        # an event appears here once it has at least one graded pick; its no-pick rows ride along as a count
        out["by_event"] = [{"event": e, "date": x["event_date"].iloc[0], "n": int(len(x)), "correct": int(x["correct_b"].sum()),
                            "no_pick": int((no_pick["event"] == e).sum()), "log_loss": round(float(x["ll"].mean()), 4)}
                           for e, x in g.groupby("event", sort=False)]
        out["by_event"].sort(key=lambda d: d["date"], reverse=True)
    out["upcoming"] = [{"event": e, "date": x["event_date"].iloc[0], "picks": int((x["pick"] != NO_PICK).sum()),
                        "no_pick": int((x["pick"] == NO_PICK).sum()), "locked_at_utc": x["predicted_at_utc"].min()}
                       for e, x in pending.groupby("event", sort=False)]
    out["upcoming"].sort(key=lambda d: d["date"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "picks_summary.json").write_text(json.dumps(out, indent=2, default=str))
    return out


# ---------- 5. cumulative record ----------

def cumulative_series(ledger: pd.DataFrame) -> dict:
    """The running record after each graded pick, in grading order (graded_at_utc, then result date, then ledger
    order), as {"v10": [...], "v11": [...]} for the v1.0 pick and the shadow pick. Each point carries n, correct,
    accuracy and the Wilson 95% interval, plus the pick_id, event_date and graded_at_utc it was reached at. A row
    counts for a series only when that series made a pick on it and the bout had a winner, so a v1.0 "no pick" row
    is left out of v10 but can still count for v11, and the other way round."""
    out: dict = {"v10": [], "v11": []}
    if ledger.empty:
        return out
    done = ledger[ledger["status"].isin(["correct", "incorrect", NO_PICK_BAND])].copy()
    if done.empty:
        return out
    done["_pos"] = range(len(done))
    done = done.sort_values(["graded_at_utc", "result_date", "_pos"])
    winner = done["winner"].map(norm)
    masks = {"v10": (done["status"].isin(["correct", "incorrect"]), done["status"] == "correct"),
             "v11": (~done["pick_v11"].isin(["", NO_PICK]) & (done["winner"] != ""), done["pick_v11"].map(norm) == winner)}
    for key, (picked, hit) in masks.items():
        k = 0
        for n, (i, r) in enumerate(done[picked].iterrows(), start=1):
            k += int(hit.loc[i])
            out[key].append({"n": n, "correct": k, "accuracy": round(k / n, 4), "wilson95": _wilson(k, n),
                             "pick_id": r["pick_id"], "event_date": r["event_date"], "graded_at_utc": r["graded_at_utc"]})
    return out


_SVG_FONT = "system-ui, -apple-system, Segoe UI, sans-serif"
_INK = {"surface": "#fcfcfb", "text": "#0b0b0b", "text2": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
        "v10": "#2a78d6", "v11": "#eb6834"}


def cumulative_chart_svg(series: dict) -> str:
    """An inline SVG of the running accuracy from cumulative_series(): the v1.0 line with its shaded Wilson 95% band,
    a thinner dashed line for the shadow pick, a dotted 50% reference, five y ticks and a legend that carries the
    current record. Sized by viewBox (340 x 232 units) so it scales to its container and stays readable at 320 px.
    No scripts, fonts or external references; with nothing graded it says so."""
    v10, v11 = series.get("v10", []), series.get("v11", [])
    W, H = 340, 232
    x0, x1, y0, y1 = 42, 294, 78, 192
    pw, ph = x1 - x0, y1 - y0
    n_max = max(len(v10), len(v11), 1)
    esc = html.escape

    def fx(n: int) -> float:
        return x0 + pw * n / n_max

    def fy(acc: float) -> float:
        return y1 - ph * acc

    def pts(points: list[dict]) -> str:
        return " ".join(f"{fx(p['n']):.1f},{fy(p['accuracy']):.1f}" for p in points)

    def record(points: list[dict]) -> str:
        last = points[-1]
        return f"{last['correct']} of {last['n']} correct ({last['accuracy']:.1%})"

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-labelledby="pk-title pk-desc" '
             f'style="width:100%;height:auto;display:block" font-family="{_SVG_FONT}">']
    title = "Cumulative accuracy of pre-event picks"
    if v10 or v11:
        desc = "; ".join(f"{lbl}: {record(s)}, 95% interval {s[-1]['wilson95'][0]:.0%} to {s[-1]['wilson95'][1]:.0%}"
                         for lbl, s in (("v1.0", v10), ("shadow v1.1", v11)) if s)
    else:
        desc = "No graded picks yet"
    parts.append(f'<title id="pk-title">{esc(title)}</title><desc id="pk-desc">{esc(desc)}</desc>')
    parts.append(f'<rect width="{W}" height="{H}" fill="{_INK["surface"]}"/>')
    parts.append(f'<text x="10" y="18" font-size="12.5" font-weight="600" fill="{_INK["text"]}">{esc(title)}</text>')

    # legend: identity plus the current record, so the numbers are readable without a tooltip layer
    if v10:
        label = f"v1.0 pick: {record(v10)}"
        parts.append(f'<line x1="10" y1="34" x2="30" y2="34" stroke="{_INK["v10"]}" stroke-width="2" stroke-linecap="round"/>'
                     f'<text x="36" y="37.5" font-size="10" fill="{_INK["text2"]}">{esc(label)}</text>')
        bx = 36 + len(label) * 5.3 + 14
        parts.append(f'<rect x="{bx:.1f}" y="29" width="20" height="10" fill="{_INK["v10"]}" fill-opacity="0.14"/>'
                     f'<text x="{bx + 26:.1f}" y="37.5" font-size="10" fill="{_INK["text2"]}">95% interval</text>')
    if v11:
        parts.append(f'<line x1="10" y1="50" x2="30" y2="50" stroke="{_INK["v11"]}" stroke-width="1.4" stroke-dasharray="4 3"/>'
                     f'<text x="36" y="53.5" font-size="10" fill="{_INK["text2"]}">Shadow v1.1: {esc(record(v11))}</text>')

    # axes: five y ticks (0 to 100%), the 50% line dotted as the coin-flip reference, at most six x ticks
    parts.append(f'<text x="10" y="{y0 - 9}" font-size="10" fill="{_INK["text2"]}">Accuracy</text>')
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = fy(tick)
        if tick == 0.5:
            parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{_INK["muted"]}" stroke-width="1" stroke-dasharray="2 3"/>')
        elif tick > 0:
            parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{_INK["grid"]}" stroke-width="1"/>')
        parts.append(f'<text x="{x0 - 6}" y="{y + 3.5:.1f}" font-size="10" text-anchor="end" fill="{_INK["muted"]}">{tick:.0%}</text>')
    if v10 or v11:
        step = next((s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000) if n_max // s <= 5), 10000)
        for n in range(0, n_max + 1, step):
            x = fx(n)
            parts.append(f'<line x1="{x:.1f}" y1="{y1}" x2="{x:.1f}" y2="{y1 + 4}" stroke="{_INK["axis"]}" stroke-width="1"/>'
                         f'<text x="{x:.1f}" y="{y1 + 15}" font-size="10" text-anchor="middle" fill="{_INK["muted"]}">{n}</text>')
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="{_INK["axis"]}" stroke-width="1"/>'
                 f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{_INK["axis"]}" stroke-width="1"/>')
    parts.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{H - 8}" font-size="10" text-anchor="middle" fill="{_INK["text2"]}">'
                 f'Picks graded, in grading order</text>')

    if not (v10 or v11):
        parts.append(f'<text x="10" y="37.5" font-size="10" fill="{_INK["text2"]}">Picks are graded once results reach UFCStats.</text>'
                     f'<text x="{(x0 + x1) / 2:.1f}" y="{fy(0.625) + 4:.1f}" font-size="12" text-anchor="middle" '
                     f'fill="{_INK["text2"]}">No graded picks yet</text></svg>')
        return "".join(parts)

    # v1.0: Wilson band, line, end marker and end label
    if v10:
        if len(v10) == 1:
            lo, hi = v10[0]["wilson95"]
            parts.append(f'<line x1="{fx(1):.1f}" y1="{fy(hi):.1f}" x2="{fx(1):.1f}" y2="{fy(lo):.1f}" stroke="{_INK["v10"]}" '
                         f'stroke-opacity="0.25" stroke-width="6"/>')
        else:
            upper = " ".join(f"{fx(p['n']):.1f},{fy(p['wilson95'][1]):.1f}" for p in v10)
            lower = " ".join(f"{fx(p['n']):.1f},{fy(p['wilson95'][0]):.1f}" for p in reversed(v10))
            parts.append(f'<polygon points="{upper} {lower}" fill="{_INK["v10"]}" fill-opacity="0.14"/>')
        parts.append(f'<polyline points="{pts(v10)}" fill="none" stroke="{_INK["v10"]}" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
    if v11:
        parts.append(f'<polyline points="{pts(v11)}" fill="none" stroke="{_INK["v11"]}" stroke-width="1.4" stroke-dasharray="4 3" '
                     f'stroke-linejoin="round"/>')
        ex, ey = fx(v11[-1]["n"]), fy(v11[-1]["accuracy"])
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2.8" fill="{_INK["v11"]}" stroke="{_INK["surface"]}" stroke-width="1.5"/>')
        if not v10 or abs(ey - fy(v10[-1]["accuracy"])) >= 11:
            parts.append(f'<text x="{ex + 7:.1f}" y="{ey + 3.5:.1f}" font-size="10" fill="{_INK["text2"]}">{v11[-1]["accuracy"]:.1%}</text>')
    if v10:
        ex, ey = fx(v10[-1]["n"]), fy(v10[-1]["accuracy"])
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3.5" fill="{_INK["v10"]}" stroke="{_INK["surface"]}" stroke-width="1.5"/>'
                     f'<text x="{ex + 7:.1f}" y="{ey + 3.5:.1f}" font-size="10" font-weight="600" fill="{_INK["text"]}">{v10[-1]["accuracy"]:.1%}</text>')
    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    cfg = _cfg()
    bouts = pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])
    data_through = bouts["date"].max()
    data = fetch(cfg["horizon_days"])
    problems = validate_feed(data) if data is not None else ["no schedule payload: the feed was not reachable and there is no saved copy"]
    upcoming = pd.DataFrame()
    if not problems:
        try:
            upcoming = parse_upcoming(data, data_through)
        except Exception as e:  # noqa: BLE001 - a feed the check did not foresee must not take grading down with it
            problems = [f"parse_upcoming failed: {type(e).__name__}: {e}"]
    feed_status = {"ok": not problems, "checked_at_utc": _now()}
    if problems:
        feed_status["problems"] = problems
        print("picks: WARNING the schedule feed failed the schema check; no picks are locked this run")
        for p in problems:
            print(f"  - {p}")
    ledger = lock(upcoming, data_through)   # with no upcoming bouts this only fills missing shadow picks
    ledger = grade(ledger, data_through)
    s = summarize(ledger, feed_status)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "picks_cumulative.svg").write_text(cumulative_chart_svg(cumulative_series(ledger)))
    print(json.dumps({k: s[k] for k in ("graded", "pending", "void", "no_pick", "record", "feed_status") if k in s}, indent=1))


if __name__ == "__main__":
    main()
