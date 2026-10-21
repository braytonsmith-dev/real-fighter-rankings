"""
odds.py - Market baseline for the pre-event picks: a de-vigged bookmaker consensus per bout, recorded when the
model's pick is locked and again on the last run before the event, so a miss can be read as the model's or everyone's.

Flow (picks.py calls snapshot() after lock() and market_baseline() inside summarize(); nothing here edits picks.csv):
  1. fetch_upcoming    one GET to The Odds API for upcoming MMA head-to-head prices; key from ODDS_API_KEY only
  2. parse_markets     one row per (bout, bookmaker) with decimal prices and the commence time
  3. consensus         per bout: de-vig each book (normalise 1/price over the two fighters), then average across books
  4. match_to_picks    same name normalisation and alias map as picks.py uses for the ESPN feed, date within window_days
  5. label_snapshots   "lock" the first time a bout is seen; "last_before_event" when the next scheduled run is after the bout
  6. record            append-only ledger predictions/market_at_lock.csv keyed by (fighter_a, fighter_b, event_date, snapshot_kind)
  7. market_baseline   accuracy and log loss of the market favourite and probability against the model on the same graded bouts

What is stored publicly (config/odds.yaml, store_raw_prices): derived values only by default, that is the de-vigged
consensus probability per fighter, the market favourite and the number of books. Per-bookmaker prices and the
min/max price range are written only when the owner sets store_raw_prices: true. Raw API responses never touch disk.
Terms and citations: MARKET_BASELINE.md.

    PYTHONPATH=src python3 -m mmalab.odds             # one snapshot against predictions/picks.csv (enabled: true and ODDS_API_KEY)
    PYTHONPATH=src python3 -m mmalab.odds --dry-run   # fetch and print the matches, write nothing (ignores enabled: false)
    PYTHONPATH=src python3 -m mmalab.odds --baseline  # print market_baseline() from the ledgers on disk
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.compare import norm

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"
ENV_KEY = "ODDS_API_KEY"

PARSED_COLUMNS = ["event_id", "commence_time", "fighter_home", "fighter_away", "book", "book_title", "last_update",
                  "price_home", "price_away"]
CONSENSUS_COLUMNS = ["event_id", "commence_time", "fighter_home", "fighter_away", "n_books", "p_home", "p_away",
                     "price_home_min", "price_home_max", "price_away_min", "price_away_max", "fetched_at_utc"]
MATCHED_COLUMNS = ["pick_id", "fighter_a", "fighter_b", "event_date", "commence_time_utc", "fetched_at_utc", "n_books",
                   "p_a_market", "p_b_market", "market_favourite", "price_a_min", "price_a_max", "price_b_min", "price_b_max"]
LEDGER_COLUMNS = ["pick_id", "fighter_a", "fighter_b", "event_date", "snapshot_kind", "fetched_at_utc", "commence_time_utc",
                  "n_books", "p_a_market", "p_b_market", "market_favourite",
                  "price_a_min", "price_a_max", "price_b_min", "price_b_max", "provider", "regions", "markets"]
BOOKS_COLUMNS = ["pick_id", "fighter_a", "fighter_b", "event_date", "snapshot_kind", "fetched_at_utc", "book", "book_title",
                 "last_update", "price_a", "price_b"]
PRICE_COLUMNS = ["price_a_min", "price_a_max", "price_b_min", "price_b_max"]
SNAPSHOT_KINDS = ("lock", "last_before_event")

HttpGet = Callable[[str, float], tuple[int, dict, bytes]]


class OddsError(RuntimeError):
    """A configuration, budget, network or API problem, with a message the owner can act on."""


# ---------- config and small helpers ----------

def _cfg(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CFG / "odds.yaml").read_text())


def _aliases() -> dict:
    """Same map picks.py builds: normalised external spelling -> normalised UFCStats spelling."""
    p = CFG / "name_aliases.yaml"
    raw = yaml.safe_load(p.read_text()) if p.exists() else None
    return {norm(k): norm(v) for k, v in (raw or {}).items()}


def _canon(name: str, aliases: dict) -> str:
    k = norm(name)
    return aliases.get(k, k)


def _pair_key(a: str, b: str, aliases: dict) -> str:
    return " | ".join(sorted((_canon(a, aliases), _canon(b, aliases))))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def api_key_from_env() -> str | None:
    """The key comes from the environment variable ODDS_API_KEY and nowhere else."""
    key = os.environ.get(ENV_KEY, "").strip()
    return key or None


def request_cost(cfg: dict) -> int:
    """The Odds API charges one credit per region per market for a call to the odds endpoint."""
    return max(1, len(cfg.get("regions") or [])) * max(1, len(cfg.get("markets") or []))


def build_url(cfg: dict, api_key: str) -> str:
    params = {"apiKey": api_key, "regions": ",".join(cfg["regions"]), "markets": ",".join(cfg.get("markets") or ["h2h"]),
              "oddsFormat": cfg.get("odds_format", "decimal"), "dateFormat": "iso"}
    return f"{cfg['base_url'].rstrip('/')}/sports/{cfg['sport_key']}/odds/?{urllib.parse.urlencode(params)}"


def redact(url: str) -> str:
    """The request URL with the key blanked, safe for logs."""
    return re.sub(r"(apiKey=)[^&]*", r"\1***", url)


def _aware(dt: datetime) -> datetime:
    """Naive datetimes are taken as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _bout_key(a: str, b: str, event_date: str) -> tuple:
    return (frozenset((norm(a), norm(b))), str(event_date))


# ---------- 1. fetch ----------

def _urllib_get(url: str, timeout: float) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "real-fighter-rankings/1.0 (research; github.com/braytonsmith-dev/real-fighter-rankings)",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


def fetch_upcoming(api_key: str | None, cfg: dict | None = None, http: HttpGet | None = None) -> dict:
    """GET the upcoming MMA head-to-head odds from The Odds API.

    Returns {"fetched_at_utc", "url" (key redacted), "cost", "requests_remaining", "requests_used", "events": [...]}.
    Raises OddsError with a plain-language message when the key is missing, the call would exceed the per-run budget,
    the network is unreachable, or the API answers with an error. A missing api_key falls back to ODDS_API_KEY.
    """
    cfg = cfg or _cfg()
    key = api_key or api_key_from_env()
    if not key:
        raise OddsError(f"no API key: set the environment variable {ENV_KEY} (GitHub Actions secret of the same name)")
    cost = request_cost(cfg)
    budget = int(cfg.get("max_requests_per_run", cost))
    if cost > budget:
        raise OddsError(f"one call costs {cost} credits ({len(cfg['regions'])} regions x {len(cfg['markets'])} markets) "
                        f"but max_requests_per_run is {budget}; trim regions or markets in config/odds.yaml")
    url = build_url(cfg, key)
    get = http or _urllib_get
    try:
        status, headers, body = get(url, float(cfg.get("timeout_seconds", 30)))
    except urllib.error.URLError as e:
        raise OddsError(f"The Odds API is not reachable ({e.reason}); nothing recorded this run") from e
    except (TimeoutError, OSError) as e:
        raise OddsError(f"The Odds API did not answer ({type(e).__name__}); nothing recorded this run") from e
    if status != 200:
        detail = ""
        try:
            detail = json.loads(body.decode("utf-8")).get("message", "")
        except (ValueError, AttributeError, UnicodeDecodeError):
            detail = body[:200].decode("utf-8", "replace") if body else ""
        hint = {401: f"the key was rejected or the account has no credits left; check the {ENV_KEY} secret and the plan quota",
                404: f"unknown sport key {cfg['sport_key']!r} or endpoint; check base_url and sport_key",
                422: "invalid parameters; check regions, markets and odds_format in config/odds.yaml",
                429: "rate limited; the API asks for requests to be spaced out over several seconds"}.get(status, "unexpected answer")
        raise OddsError(f"The Odds API returned HTTP {status}: {hint}" + (f" ({detail})" if detail else ""))
    try:
        events = json.loads(body.decode("utf-8"))
    except ValueError as e:
        raise OddsError("The Odds API returned a body that is not JSON") from e
    if not isinstance(events, list):
        raise OddsError(f"unexpected payload type {type(events).__name__}; expected a list of events")
    remaining = headers.get("x-requests-remaining", "")
    out = {"fetched_at_utc": _stamp(_now()), "url": redact(url), "cost": cost, "sport_key": cfg["sport_key"],
           "regions": ",".join(cfg["regions"]), "markets": ",".join(cfg.get("markets") or ["h2h"]),
           "requests_remaining": remaining, "requests_used": headers.get("x-requests-used", ""), "events": events}
    try:
        if remaining != "" and int(float(remaining)) < int(cfg.get("min_remaining_credits", 0)):
            print(f"odds: WARNING only {remaining} credits left on the plan this month (min_remaining_credits={cfg.get('min_remaining_credits')})")
    except ValueError:
        pass
    return out


# ---------- 2. parse ----------

def _price(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v if math.isfinite(v) and v > 1.0 else float("nan")


def parse_markets(payload: dict | list) -> pd.DataFrame:
    """One row per (bout, bookmaker) from the documented v4 odds payload.

    Accepts the dict returned by fetch_upcoming or the raw list from the API. Only the "h2h" market is read (the
    exchanges' "h2h_lay" market is skipped); outcomes that are neither fighter (a "Draw" line) are ignored, and a
    bookmaker without a valid price (> 1.0) for both fighters is dropped.
    """
    events = payload.get("events", []) if isinstance(payload, dict) else (payload or [])
    rows = []
    for ev in events:
        home, away = ev.get("home_team") or "", ev.get("away_team") or ""
        if not home or not away:
            continue
        for bk in ev.get("bookmakers") or []:
            for mk in bk.get("markets") or []:
                if mk.get("key") != "h2h":
                    continue
                ph = pa = float("nan")
                for oc in mk.get("outcomes") or []:
                    name = str(oc.get("name") or "")
                    if name == home or (name and norm(name) == norm(home)):
                        ph = _price(oc.get("price"))
                    elif name == away or (name and norm(name) == norm(away)):
                        pa = _price(oc.get("price"))
                if math.isnan(ph) or math.isnan(pa):
                    continue
                rows.append({"event_id": str(ev.get("id") or ""), "commence_time": ev.get("commence_time") or "",
                             "fighter_home": home, "fighter_away": away, "book": bk.get("key") or "", "book_title": bk.get("title") or "",
                             "last_update": mk.get("last_update") or bk.get("last_update") or "", "price_home": ph, "price_away": pa})
    return pd.DataFrame(rows, columns=PARSED_COLUMNS)


# ---------- 3. consensus ----------

def consensus(df: pd.DataFrame, fetched_at: str | None = None, min_books: int = 1) -> pd.DataFrame:
    """Per bout: de-vigged implied probability for each fighter, averaged across books.

    Each book's pair of decimal prices is turned into 1/price and normalised to sum to one (the over-round removed
    proportionally), then the per-book probabilities are averaged. p_home + p_away is exactly 1 per bout.
    Also returns the number of books and the min and max decimal price per fighter.
    """
    fetched = fetched_at or _stamp(_now())
    if df.empty:
        return pd.DataFrame(columns=CONSENSUS_COLUMNS)
    d = df.copy()
    d["inv_h"], d["inv_a"] = 1.0 / d["price_home"].astype(float), 1.0 / d["price_away"].astype(float)
    d["p_h_book"] = d["inv_h"] / (d["inv_h"] + d["inv_a"])
    g = d.groupby(["event_id", "commence_time", "fighter_home", "fighter_away"], sort=False)
    out = g.agg(n_books=("book", "nunique"), p_home=("p_h_book", "mean"),
                price_home_min=("price_home", "min"), price_home_max=("price_home", "max"),
                price_away_min=("price_away", "min"), price_away_max=("price_away", "max")).reset_index()
    out["p_away"] = 1.0 - out["p_home"]
    out["fetched_at_utc"] = fetched
    out = out[out["n_books"] >= int(min_books)]
    return out[CONSENSUS_COLUMNS].reset_index(drop=True)


# ---------- 4. match ----------

def match_to_picks(consensus_df: pd.DataFrame, picks_df: pd.DataFrame, aliases: dict | None = None, window_days: int = 2) -> pd.DataFrame:
    """Join consensus bouts to ledger rows by normalised name pair and date.

    Names go through mmalab.compare.norm and the config/name_aliases.yaml map, the way picks.py matches the ESPN
    feed to UFCStats. A bout matches a pick when the pair is the same and the commence time (UTC) is within
    window_days of the ledger's event_date. Probabilities are re-oriented to the pick's fighter_a / fighter_b.
    One row per matched pick; if several market bouts match, the one with the most books (then the nearest date) wins.
    """
    aliases = _aliases() if aliases is None else aliases
    if consensus_df.empty or picks_df.empty:
        return pd.DataFrame(columns=MATCHED_COLUMNS)
    c = consensus_df.copy()
    c["key"] = [_pair_key(h, a, aliases) for h, a in zip(c["fighter_home"], c["fighter_away"])]
    c["home_canon"] = [_canon(h, aliases) for h in c["fighter_home"]]
    c["commence_utc"] = [_utc(t) if t else pd.NaT for t in c["commence_time"]]
    p = picks_df.copy()
    p["key"] = [_pair_key(a, b, aliases) for a, b in zip(p["fighter_a"], p["fighter_b"])]
    p["a_canon"] = [_canon(a, aliases) for a in p["fighter_a"]]
    p["ev_date"] = pd.to_datetime(p["event_date"], errors="coerce")
    m = p.merge(c, on="key", how="inner", suffixes=("", "_mkt"))
    if m.empty:
        return pd.DataFrame(columns=MATCHED_COLUMNS)
    m["gap_days"] = [abs((t.tz_convert(None).normalize() - d).days) if not (pd.isna(t) or pd.isna(d)) else 10 ** 6
                     for t, d in zip(m["commence_utc"], m["ev_date"])]
    m = m[m["gap_days"] <= int(window_days)]
    if m.empty:
        return pd.DataFrame(columns=MATCHED_COLUMNS)
    m = m.sort_values(["n_books", "gap_days"], ascending=[False, True]).drop_duplicates("pick_id", keep="first")
    same = m["home_canon"] == m["a_canon"]
    rows = pd.DataFrame({
        "pick_id": m["pick_id"].values, "fighter_a": m["fighter_a"].values, "fighter_b": m["fighter_b"].values,
        "event_date": m["event_date"].values, "commence_time_utc": [_stamp(t.to_pydatetime()) for t in m["commence_utc"]],
        "fetched_at_utc": m["fetched_at_utc"].values, "n_books": m["n_books"].astype(int).values,
        "p_a_market": np.where(same, m["p_home"], m["p_away"]).round(4),
        "price_a_min": np.where(same, m["price_home_min"], m["price_away_min"]).round(3),
        "price_a_max": np.where(same, m["price_home_max"], m["price_away_max"]).round(3),
        "price_b_min": np.where(same, m["price_away_min"], m["price_home_min"]).round(3),
        "price_b_max": np.where(same, m["price_away_max"], m["price_home_max"]).round(3),
    })
    rows["p_b_market"] = (1.0 - rows["p_a_market"]).round(4)
    rows["market_favourite"] = np.where(rows["p_a_market"] >= 0.5, rows["fighter_a"], rows["fighter_b"])   # same rule as the model's pick
    return rows[MATCHED_COLUMNS].reset_index(drop=True)


# ---------- 5. snapshot kinds ----------

def next_scheduled_run(now: datetime, weekdays: list[int], hour: int) -> datetime:
    """The first scheduled run (UTC, on the hour) strictly after now; weekdays use Monday = 0."""
    base = _aware(now)
    for d in range(0, 8):
        cand = (base + timedelta(days=d)).replace(hour=int(hour), minute=0, second=0, microsecond=0)
        if cand.weekday() in set(int(w) for w in weekdays) and cand > base:
            return cand
    raise OddsError("schedule_utc.weekdays in config/odds.yaml is empty")


def label_snapshots(matched: pd.DataFrame, now: datetime | None = None, weekdays: list[int] | None = None, hour: int = 13) -> pd.DataFrame:
    """Expand matched bouts into ledger candidates with a snapshot_kind.

    Every bout that has not started gets a "lock" candidate (record() keeps only the first one ever written).
    It also gets a "last_before_event" candidate when the next scheduled run falls after its commence time, so the
    Friday 13:00 UTC run is the last one before a Saturday card and the Monday run is the last one before a
    Tuesday or Wednesday card. Bouts whose commence time has passed (live or finished) get no candidate.
    """
    now = _aware(now or _now())
    weekdays = [0, 4] if weekdays is None else weekdays
    if matched.empty:
        return pd.DataFrame(columns=MATCHED_COLUMNS + ["snapshot_kind"])
    nxt = next_scheduled_run(now, weekdays, hour)
    out = []
    for r in matched.to_dict("records"):
        start = _utc(r["commence_time_utc"]).to_pydatetime() if r.get("commence_time_utc") else None
        if start is not None and start <= now:
            continue
        out.append({**r, "snapshot_kind": "lock"})
        if start is not None and nxt > start:
            out.append({**r, "snapshot_kind": "last_before_event"})
    return pd.DataFrame(out, columns=MATCHED_COLUMNS + ["snapshot_kind"])


# ---------- 6. record ----------

def _ledger_key(a: str, b: str, event_date: str, kind: str) -> tuple:
    return _bout_key(a, b, event_date) + (str(kind),)


def load_market(path: str | Path | None = None) -> pd.DataFrame:
    p = ROOT / (path or _cfg().get("ledger", "predictions/market_at_lock.csv"))
    if not p.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    for c in LEDGER_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[LEDGER_COLUMNS]


def record(matched: pd.DataFrame, path: str | Path = "predictions/market_at_lock.csv", store_raw_prices: bool = False) -> pd.DataFrame:
    """Append new (fighter_a, fighter_b, event_date, snapshot_kind) rows to the public market ledger; return them.

    Existing rows are never edited or re-ordered: the key check is order-insensitive on the two names, so a bout
    re-listed with the fighters swapped is still the same bout. Rows without a snapshot_kind column count as
    "lock". When store_raw_prices is false the min/max price columns are left blank (derived probabilities only).
    """
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    existing = load_market(p) if p.exists() else pd.DataFrame(columns=LEDGER_COLUMNS)
    seen = {_ledger_key(a, b, d, k) for a, b, d, k in zip(existing["fighter_a"], existing["fighter_b"], existing["event_date"], existing["snapshot_kind"])}
    if matched.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    m = matched.copy()
    if "snapshot_kind" not in m.columns:
        m["snapshot_kind"] = "lock"
    for c in LEDGER_COLUMNS:
        if c not in m.columns:
            m[c] = ""
    rows = []
    for r in m[LEDGER_COLUMNS].to_dict("records"):
        if r["snapshot_kind"] not in SNAPSHOT_KINDS:
            raise OddsError(f"unknown snapshot_kind {r['snapshot_kind']!r}; expected one of {SNAPSHOT_KINDS}")
        k = _ledger_key(r["fighter_a"], r["fighter_b"], r["event_date"], r["snapshot_kind"])
        if k in seen:
            continue
        seen.add(k)
        if not store_raw_prices:
            for c in PRICE_COLUMNS:
                r[c] = ""
        rows.append({c: ("" if (isinstance(v, float) and math.isnan(v)) else v) for c, v in r.items()})
    new = pd.DataFrame(rows, columns=LEDGER_COLUMNS).astype(str)
    if new.empty:
        return new
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([existing.astype(str), new], ignore_index=True).to_csv(p, index=False)
    return new


def record_books(parsed: pd.DataFrame, new_rows: pd.DataFrame, consensus_df: pd.DataFrame, path: str | Path, aliases: dict | None = None) -> pd.DataFrame:
    """Per-bookmaker prices for the bouts just added to the ledger; only called when store_raw_prices is true.
    Append-only, keyed by (fighter_a, fighter_b, event_date, snapshot_kind, book)."""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if parsed.empty or new_rows.empty:
        return pd.DataFrame(columns=BOOKS_COLUMNS)
    aliases = _aliases() if aliases is None else aliases
    existing = pd.read_csv(p, dtype=str, keep_default_na=False) if p.exists() else pd.DataFrame(columns=BOOKS_COLUMNS)
    seen = {(frozenset((norm(a), norm(b))), d, k, bk) for a, b, d, k, bk in
            zip(existing["fighter_a"], existing["fighter_b"], existing["event_date"], existing["snapshot_kind"], existing["book"])}
    by_key = {}
    for r in parsed.to_dict("records"):
        by_key.setdefault(_pair_key(r["fighter_home"], r["fighter_away"], aliases), []).append(r)
    rows = []
    for r in new_rows.to_dict("records"):
        a_canon = _canon(r["fighter_a"], aliases)
        for bk in by_key.get(_pair_key(r["fighter_a"], r["fighter_b"], aliases), []):
            k = (frozenset((norm(r["fighter_a"]), norm(r["fighter_b"]))), str(r["event_date"]), r["snapshot_kind"], bk["book"])
            if k in seen:
                continue
            seen.add(k)
            same = _canon(bk["fighter_home"], aliases) == a_canon
            rows.append({"pick_id": r["pick_id"], "fighter_a": r["fighter_a"], "fighter_b": r["fighter_b"], "event_date": r["event_date"],
                         "snapshot_kind": r["snapshot_kind"], "fetched_at_utc": r["fetched_at_utc"], "book": bk["book"], "book_title": bk["book_title"],
                         "last_update": bk["last_update"], "price_a": bk["price_home"] if same else bk["price_away"],
                         "price_b": bk["price_away"] if same else bk["price_home"]})
    new = pd.DataFrame(rows, columns=BOOKS_COLUMNS).astype(str)
    if new.empty:
        return new
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([existing.astype(str), new], ignore_index=True).to_csv(p, index=False)
    return new


# ---------- 7. baseline ----------

def _logloss(y: np.ndarray, p: np.ndarray) -> float:
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(pc) + (1 - y) * np.log(1 - pc)).mean())


def market_baseline(picks_df: pd.DataFrame, market_df: pd.DataFrame, cfg: dict | None = None) -> dict:
    """Market favourite and de-vigged probability against the model on the same graded bouts, per snapshot kind.

    "baselines_same_bouts" has the shape picks.summarize() already uses for its other baselines, so it can be merged
    into that block of outputs/picks_summary.json; "detail" adds Brier, the agreement rate between the model's pick and
    the market favourite, the split record on the bouts where they disagree, and the mean number of books.
    """
    cfg = cfg or _cfg()
    out = {"provider": cfg.get("provider", ""), "attribution": cfg.get("attribution", ""), "ledger": cfg.get("ledger", ""),
           "store_raw_prices": bool(cfg.get("store_raw_prices", False)), "favourite_rule": "fighter_a when p_a_market >= 0.5, same convention as the model's pick",
           "graded_with_market": 0, "graded_without_market": 0, "baselines_same_bouts": {}, "detail": {}}
    if picks_df is None or picks_df.empty or market_df is None or market_df.empty:
        g = picks_df[picks_df["status"].isin(["correct", "incorrect"])] if picks_df is not None and not picks_df.empty else pd.DataFrame()
        out["graded_without_market"] = int(len(g))
        return out
    g = picks_df[picks_df["status"].isin(["correct", "incorrect"]) & (picks_df["winner"].astype(str) != "")].copy()
    if g.empty:
        return out
    g["key"] = [_bout_key(a, b, d) for a, b, d in zip(g["fighter_a"], g["fighter_b"], g["event_date"])]
    g["a_n"] = g["fighter_a"].map(norm)
    g["y_a"] = (g["winner"].map(norm) == g["a_n"]).astype(float)
    g["model_pick_a"] = g["pick"].map(norm) == g["a_n"]
    g["model_correct"] = g["correct"].astype(str) == "True"
    g["model_p"] = pd.to_numeric(g["p_a"], errors="coerce")
    ll_col = pd.to_numeric(g["log_loss"], errors="coerce")
    g["model_ll"] = ll_col.where(ll_col.notna(), -(g["y_a"] * np.log(g["model_p"].clip(1e-6, 1 - 1e-6)) + (1 - g["y_a"]) * np.log(1 - g["model_p"].clip(1e-6, 1 - 1e-6))))
    g["model_brier"] = (g["model_p"] - g["y_a"]) ** 2
    mk = market_df.copy()
    mk["key"] = [_bout_key(a, b, d) for a, b, d in zip(mk["fighter_a"], mk["fighter_b"], mk["event_date"])]
    mk["a_n"] = mk["fighter_a"].map(norm)
    mk["p"] = pd.to_numeric(mk["p_a_market"], errors="coerce")
    mk["books"] = pd.to_numeric(mk["n_books"], errors="coerce")
    for kind in SNAPSHOT_KINDS:
        s = mk[(mk["snapshot_kind"] == kind) & mk["p"].notna()].drop_duplicates("key")
        if s.empty:
            continue
        j = g.merge(s[["key", "a_n", "p", "books"]].rename(columns={"a_n": "mkt_a_n"}), on="key", how="inner")
        if j.empty:
            continue
        p_a = np.where(j["mkt_a_n"] == j["a_n"], j["p"], 1 - j["p"]).astype(float)
        y = j["y_a"].to_numpy(dtype=float)
        fav_a = p_a >= 0.5
        fav_correct = (fav_a == (y == 1.0))
        agree = (fav_a == j["model_pick_a"].to_numpy())
        dis = ~agree
        block = {"n": int(len(j)), "accuracy": round(float(fav_correct.mean()), 3), "log_loss": round(_logloss(y, p_a), 4),
                 "model_accuracy_same_bouts": round(float(j["model_correct"].mean()), 3),
                 "model_log_loss_same_bouts": round(float(j["model_ll"].mean()), 4)}
        out["baselines_same_bouts"][f"market_devigged_{kind}"] = block
        out["detail"][kind] = {
            **block, "brier": round(float(((p_a - y) ** 2).mean()), 4), "model_brier_same_bouts": round(float(j["model_brier"].mean()), 4),
            "pickem_bouts": int((p_a == 0.5).sum()), "mean_n_books": round(float(j["books"].mean()), 1) if j["books"].notna().any() else None,
            "agreement_rate": round(float(agree.mean()), 3),
            "when_model_and_market_disagree": {"n": int(dis.sum()), "model_correct": int(j["model_correct"].to_numpy()[dis].sum()),
                                               "market_correct": int(fav_correct[dis].sum())},
            "mean_market_p_for_model_pick": round(float(np.where(j["model_pick_a"].to_numpy(), p_a, 1 - p_a).mean()), 3),
        }
        if kind == "lock":
            out["graded_with_market"] = int(len(j))
            out["graded_without_market"] = int(len(g) - len(j))
    if "lock" not in out["detail"]:
        out["graded_without_market"] = int(len(g))
    return out


# ---------- orchestration ----------

def run_report(payload: dict, cons: pd.DataFrame, pending: pd.DataFrame, matched: pd.DataFrame, now: datetime,
               aliases: dict | None = None, window_days: int = 2, horizon_days: int = 14) -> dict:
    """What one run saw, for outputs/market_last_run.json and the log: counts, credits, and the two kinds of miss
    that a spelling difference or a changed bout produces (a pending pick within `horizon_days` that found no market
    bout; a market bout within the same horizon that matched no pending pick). Names are listed so a miss can be
    fixed in config/name_aliases.yaml, the way picks.py reports ESPN misses."""
    aliases = _aliases() if aliases is None else aliases
    horizon = now + timedelta(days=horizon_days)
    got = set(matched["pick_id"]) if not matched.empty else set()
    miss_picks = []
    if not pending.empty:
        ev = pd.to_datetime(pending["event_date"], errors="coerce")
        soon = pending[(ev >= pd.Timestamp(now.date())) & (ev <= pd.Timestamp(horizon.date()))]
        miss_picks = [f"{r.fighter_a} vs {r.fighter_b} ({r.event_date})" for r in soon.itertuples() if r.pick_id not in got]
    miss_market = []
    if not cons.empty:
        matched_keys = ({_pair_key(a, b, aliases) for a, b in zip(matched["fighter_a"], matched["fighter_b"])}
                        if not matched.empty else set())
        lo, hi = pd.Timestamp(now.replace(tzinfo=None)), pd.Timestamp(horizon.replace(tzinfo=None))
        for r in cons.itertuples():
            t = _utc(r.commence_time) if r.commence_time else pd.NaT
            if pd.isna(t) or not (lo <= t.tz_convert(None) <= hi):
                continue
            if _pair_key(r.fighter_home, r.fighter_away, aliases) in matched_keys:
                continue
            miss_market.append(f"{r.fighter_home} vs {r.fighter_away} ({_stamp(t.to_pydatetime())[:10]}, {int(r.n_books)} books)")
    return {"fetched_at_utc": payload.get("fetched_at_utc"), "bouts_from_api": int(len(payload.get("events", []))),
            "bouts_with_consensus": int(len(cons)), "matched_to_pending_picks": int(len(matched)),
            "credits_remaining": payload.get("requests_remaining"), "credits_used_this_month": payload.get("requests_used"),
            "window_days": window_days, "horizon_days": horizon_days,
            "unmatched_pending_picks": miss_picks, "unmatched_market_bouts": miss_market}


def snapshot(picks_df: pd.DataFrame, now: datetime | None = None, cfg: dict | None = None, http: HttpGet | None = None,
             strict: bool = False, write: bool = True) -> pd.DataFrame:
    """One run: fetch, parse, de-vig, match pending picks, label snapshot kinds, append to the ledger. Returns the rows added.

    Returns an empty frame, after printing why, when the feature is disabled, the key is missing or the API cannot be
    reached; with strict=True those conditions raise OddsError instead. Never raises on network trouble unless strict.
    """
    cfg = cfg or _cfg()
    empty = pd.DataFrame(columns=LEDGER_COLUMNS)
    if not cfg.get("enabled", False):
        print("odds: disabled (config/odds.yaml enabled: false); no market snapshot this run")
        return empty
    now = now or _now()
    try:
        payload = fetch_upcoming(None, cfg, http=http)
    except OddsError as e:
        print(f"odds: {e}")
        if strict:
            raise
        return empty
    parsed = parse_markets(payload)
    cons = consensus(parsed, fetched_at=payload["fetched_at_utc"], min_books=int(cfg.get("min_books", 1)))
    pending = picks_df[picks_df["status"] == "pending"] if not picks_df.empty and "status" in picks_df.columns else picks_df
    aliases = _aliases()
    matched = match_to_picks(cons, pending, aliases, int(cfg.get("window_days", 2)))
    sched = cfg.get("schedule_utc") or {}
    labelled = label_snapshots(matched, now, sched.get("weekdays", [0, 4]), int(sched.get("hour", 13)))
    labelled["provider"], labelled["regions"], labelled["markets"] = cfg.get("provider", ""), payload["regions"], payload["markets"]
    print(f"odds: {len(payload['events'])} MMA bouts from the API, {len(cons)} with a consensus, {len(matched)} matched to pending picks; "
          f"{payload['requests_remaining'] or '?'} credits remaining")
    report = run_report(payload, cons, pending, matched, now, aliases, int(cfg.get("window_days", 2)))
    for line in report["unmatched_pending_picks"]:
        print(f"odds: pending pick without a market bout: {line}")
    for line in report["unmatched_market_bouts"]:
        print(f"odds: market bout without a pending pick: {line}")
    if write:
        path = Path(cfg.get("run_report", "outputs/market_last_run.json"))
        path = path if path.is_absolute() else ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))
    if not write:
        return labelled
    new = record(labelled, cfg.get("ledger", "predictions/market_at_lock.csv"), store_raw_prices=bool(cfg.get("store_raw_prices", False)))
    if cfg.get("store_raw_prices", False) and not new.empty:
        record_books(parsed, new, cons, cfg.get("books_ledger", "predictions/market_books.csv"), aliases)
    print(f"odds: {len(new)} new market row(s) appended to {cfg.get('ledger')}")
    return new


def main(argv: list[str] | None = None) -> None:
    """CLI. --dry-run fetches and prints matches without writing (ignores enabled: false); --baseline prints market_baseline()."""
    args = sys.argv[1:] if argv is None else argv
    ledger = ROOT / "predictions" / "picks.csv"
    picks = pd.read_csv(ledger, dtype=str, keep_default_na=False) if ledger.exists() else pd.DataFrame(columns=["status"])
    cfg = _cfg()
    if "--baseline" in args:
        print(json.dumps(market_baseline(picks, load_market(cfg.get("ledger")), cfg), indent=2))
        return
    if "--dry-run" in args:
        try:
            rows = snapshot(picks, cfg={**cfg, "enabled": True}, strict=True, write=False)
        except OddsError as e:
            sys.exit(f"odds: {e}")
        print(rows.to_string(index=False) if not rows.empty else "odds: no pending pick matched a market bout")
        return
    snapshot(picks, cfg=cfg)


if __name__ == "__main__":
    main()
