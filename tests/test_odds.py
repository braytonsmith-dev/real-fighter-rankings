"""Tests for src/mmalab/odds.py against a fixture in The Odds API v4 odds-endpoint shape. No network."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from mmalab import odds

ROOT = Path(__file__).resolve().parents[1]
FRI = datetime(2026, 10, 23, 13, 0, 5, tzinfo=timezone.utc)      # the Friday 13:00 UTC run before a Saturday card
MON = datetime(2026, 10, 19, 13, 0, 5, tzinfo=timezone.utc)      # the Monday run of the same week


def h2h(home: str, away: str, ph: float, pa: float, extra: list | None = None, key: str = "h2h") -> dict:
    outcomes = [{"name": home, "price": ph}, {"name": away, "price": pa}] + (extra or [])
    return {"key": key, "last_update": "2026-10-20T12:00:00Z", "outcomes": outcomes}


@pytest.fixture
def payload() -> list:
    """Two MMA bouts in the documented v4 response shape (id, sport_key, sport_title, commence_time, home_team, away_team,
    bookmakers[].key/title/last_update/markets[].key/last_update/outcomes[].name/price)."""
    return [
        {"id": "e1", "sport_key": "mma_mixed_martial_arts", "sport_title": "MMA", "commence_time": "2026-10-25T02:00:00Z",
         "home_team": "Alice Pereira", "away_team": "Daria Zhelezniakova",
         "bookmakers": [
             {"key": "draftkings", "title": "DraftKings", "last_update": "2026-10-20T12:00:00Z",
              "markets": [h2h("Alice Pereira", "Daria Zhelezniakova", 1.91, 1.91)]},
             {"key": "fanduel", "title": "FanDuel", "last_update": "2026-10-20T12:00:00Z",
              "markets": [h2h("Alice Pereira", "Daria Zhelezniakova", 1.80, 2.05)]},
             {"key": "betfair_ex_uk", "title": "Betfair Exchange", "last_update": "2026-10-20T12:00:00Z",
              "markets": [h2h("Alice Pereira", "Daria Zhelezniakova", 1.95, 2.10, key="h2h_lay")]},
             {"key": "broken", "title": "Broken Book", "last_update": "2026-10-20T12:00:00Z",
              "markets": [h2h("Alice Pereira", "Daria Zhelezniakova", 1.0, 2.0)]},
         ]},
        {"id": "e2", "sport_key": "mma_mixed_martial_arts", "sport_title": "MMA", "commence_time": "2026-10-25T02:00:00Z",
         "home_team": "King Green", "away_team": "RJ Harris",
         "bookmakers": [
             {"key": "bovada", "title": "Bovada", "last_update": "2026-10-20T12:00:00Z",
              "markets": [h2h("King Green", "RJ Harris", 1.50, 2.60, extra=[{"name": "Draw", "price": 51.0}])]},
             {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-20T12:00:00Z",
              "markets": [h2h("King Green", "RJ Harris", 1.60, 2.40)]},
         ]},
    ]


@pytest.fixture
def picks() -> pd.DataFrame:
    """Pending ledger rows: the first bout is listed with the fighters in the other order, the second uses the UFCStats
    spelling (Bobby Green) where the book says King Green, the third is the same pairing five weeks later."""
    return pd.DataFrame([
        {"pick_id": "9:1", "fighter_a": "Daria Zhelezniakova", "fighter_b": "Alice Pereira", "event_date": "2026-10-24", "status": "pending"},
        {"pick_id": "9:2", "fighter_a": "Bobby Green", "fighter_b": "RJ Harris", "event_date": "2026-10-24", "status": "pending"},
        {"pick_id": "9:3", "fighter_a": "Bobby Green", "fighter_b": "RJ Harris", "event_date": "2026-11-30", "status": "pending"},
    ])


@pytest.fixture
def cfg() -> dict:
    c = yaml.safe_load((ROOT / "config" / "odds.yaml").read_text())
    c["enabled"] = True
    return c


ALIASES = {"king green": "bobby green"}


# ---------- parse ----------

def test_parse_markets_rows_and_filters(payload):
    df = odds.parse_markets(payload)
    assert list(df.columns) == odds.PARSED_COLUMNS
    assert len(df) == 4                                   # 2 valid books for e1 (lay market and the 1.0 price dropped) + 2 for e2
    assert set(df["book"]) == {"draftkings", "fanduel", "bovada", "pinnacle"}
    e2 = df[df["event_id"] == "e2"].set_index("book")
    assert e2.loc["bovada", "price_home"] == 1.5 and e2.loc["bovada", "price_away"] == 2.6   # the Draw outcome is ignored
    assert (df["commence_time"] == "2026-10-25T02:00:00Z").all()
    assert odds.parse_markets({"events": payload}).equals(df)        # the dict from fetch_upcoming is accepted too
    assert odds.parse_markets([]).empty


# ---------- consensus ----------

def test_consensus_devig_and_sum_to_one(payload):
    cons = odds.consensus(odds.parse_markets(payload), fetched_at="2026-10-20T13:00:00Z")
    assert list(cons.columns) == odds.CONSENSUS_COLUMNS
    assert ((cons["p_home"] + cons["p_away"]) - 1.0).abs().max() < 1e-12
    e1 = cons.set_index("event_id").loc["e1"]
    # draftkings 1.91/1.91 -> 0.5/0.5; fanduel 1.80/2.05 -> 0.5325/0.4675; mean of the two
    fd = (1 / 1.80) / (1 / 1.80 + 1 / 2.05)
    assert math.isclose(e1["p_home"], (0.5 + fd) / 2, abs_tol=1e-9)
    assert e1["n_books"] == 2
    assert (e1["price_home_min"], e1["price_home_max"], e1["price_away_min"], e1["price_away_max"]) == (1.80, 1.91, 1.91, 2.05)
    assert (cons["fetched_at_utc"] == "2026-10-20T13:00:00Z").all()


def test_consensus_even_pair_is_fifty_fifty():
    one = odds.parse_markets([{"id": "x", "commence_time": "2026-10-25T02:00:00Z", "home_team": "A", "away_team": "B",
                               "bookmakers": [{"key": "k", "title": "K", "markets": [h2h("A", "B", 1.91, 1.91)]}]}])
    cons = odds.consensus(one)
    assert cons.loc[0, "p_home"] == 0.5 and cons.loc[0, "p_away"] == 0.5


def test_consensus_min_books(payload):
    cons = odds.consensus(odds.parse_markets(payload), min_books=3)
    assert cons.empty
    assert odds.consensus(pd.DataFrame(columns=odds.PARSED_COLUMNS)).empty


# ---------- match ----------

def test_match_to_picks_alias_window_and_orientation(payload, picks):
    cons = odds.consensus(odds.parse_markets(payload), fetched_at="2026-10-20T13:00:00Z")
    m = odds.match_to_picks(cons, picks, ALIASES, window_days=2).set_index("pick_id")
    assert list(m.index) == ["9:1", "9:2"]                 # 9:3 is the same pairing 36 days later: outside the window
    r = m.loc["9:1"]
    assert (r["fighter_a"], r["fighter_b"]) == ("Daria Zhelezniakova", "Alice Pereira")   # ledger order kept
    assert math.isclose(r["p_a_market"], round(1 - cons.set_index("event_id").loc["e1", "p_home"], 4), abs_tol=1e-9)
    assert r["market_favourite"] == "Alice Pereira" and r["n_books"] == 2
    assert (r["price_a_min"], r["price_a_max"]) == (1.91, 2.05)                              # re-oriented with the probabilities
    g = m.loc["9:2"]
    assert g["fighter_a"] == "Bobby Green" and g["p_a_market"] > 0.5 and g["market_favourite"] == "Bobby Green"
    assert odds.match_to_picks(cons, picks, {}, window_days=2).index.tolist() == [0]        # without the alias, King Green does not match


def test_match_window_is_in_days(payload, picks):
    cons = odds.consensus(odds.parse_markets(payload))
    assert odds.match_to_picks(cons, picks, ALIASES, window_days=0).empty          # commence 25th UTC vs event date 24th
    assert len(odds.match_to_picks(cons, picks, ALIASES, window_days=1)) == 2


# ---------- snapshot kinds ----------

def test_next_scheduled_run():
    assert odds.next_scheduled_run(FRI, [0, 4], 13) == datetime(2026, 10, 26, 13, tzinfo=timezone.utc)
    assert odds.next_scheduled_run(MON, [0, 4], 13) == datetime(2026, 10, 23, 13, tzinfo=timezone.utc)
    assert odds.next_scheduled_run(datetime(2026, 10, 23, 12, 59, tzinfo=timezone.utc), [0, 4], 13) == datetime(2026, 10, 23, 13, tzinfo=timezone.utc)
    with pytest.raises(odds.OddsError):
        odds.next_scheduled_run(FRI, [], 13)


def test_label_snapshots(payload, picks):
    m = odds.match_to_picks(odds.consensus(odds.parse_markets(payload)), picks, ALIASES, 2)
    fri = odds.label_snapshots(m, FRI, [0, 4], 13)
    assert sorted(zip(fri["pick_id"], fri["snapshot_kind"])) == [("9:1", "last_before_event"), ("9:1", "lock"), ("9:2", "last_before_event"), ("9:2", "lock")]
    mon = odds.label_snapshots(m, MON, [0, 4], 13)
    assert list(mon["snapshot_kind"]) == ["lock", "lock"]
    after = odds.label_snapshots(m, datetime(2026, 10, 25, 3, tzinfo=timezone.utc), [0, 4], 13)    # bouts already started
    assert after.empty
    assert odds.label_snapshots(m.iloc[0:0], FRI).empty


# ---------- record ----------

def test_record_is_append_only(payload, picks, tmp_path):
    path = tmp_path / "market_at_lock.csv"
    m = odds.match_to_picks(odds.consensus(odds.parse_markets(payload), fetched_at="2026-10-19T13:00:00Z"), picks, ALIASES, 2)
    first = odds.record(odds.label_snapshots(m, MON, [0, 4], 13), path)
    assert len(first) == 2 and set(first["snapshot_kind"]) == {"lock"}
    before = path.read_text()
    assert (first[odds.PRICE_COLUMNS] == "").all().all()                      # store_raw_prices defaults to false

    # Friday: prices moved, the lock rows must not change, the last_before_event rows are new
    moved = m.copy()
    moved["p_a_market"], moved["p_b_market"], moved["fetched_at_utc"] = 0.99, 0.01, "2026-10-23T13:00:00Z"
    second = odds.record(odds.label_snapshots(moved, FRI, [0, 4], 13), path)
    assert set(second["snapshot_kind"]) == {"last_before_event"} and len(second) == 2
    after = path.read_text()
    assert after.startswith(before.rstrip("\n")) and after.count("\n") == before.count("\n") + 2
    led = pd.read_csv(path, dtype=str, keep_default_na=False)
    lock = led[led["snapshot_kind"] == "lock"]
    assert (lock["fetched_at_utc"] == "2026-10-19T13:00:00Z").all() and (lock["p_a_market"].astype(float) < 0.9).all()

    # a third run with nothing new, and the same bout listed with the names swapped, writes nothing
    swapped = moved.copy()
    swapped["fighter_a"], swapped["fighter_b"] = moved["fighter_b"], moved["fighter_a"]
    third = odds.record(odds.label_snapshots(swapped, FRI, [0, 4], 13), path)
    assert third.empty and path.read_text() == after
    assert odds.record(pd.DataFrame(columns=odds.MATCHED_COLUMNS), path).empty and path.read_text() == after


def test_record_keeps_prices_only_when_allowed(payload, picks, tmp_path):
    path = tmp_path / "ledger.csv"
    m = odds.match_to_picks(odds.consensus(odds.parse_markets(payload)), picks, ALIASES, 2)
    new = odds.record(m, path, store_raw_prices=True)                                  # no snapshot_kind column: defaults to lock
    assert set(new["snapshot_kind"]) == {"lock"}
    assert (new[odds.PRICE_COLUMNS] != "").all().all()
    with pytest.raises(odds.OddsError):
        bad = m.assign(snapshot_kind="closing")
        odds.record(bad, tmp_path / "other.csv")


def test_record_books(payload, picks, tmp_path):
    parsed = odds.parse_markets(payload)
    cons = odds.consensus(parsed)
    m = odds.label_snapshots(odds.match_to_picks(cons, picks, ALIASES, 2), MON, [0, 4], 13)
    new = odds.record(m, tmp_path / "ledger.csv", store_raw_prices=True)
    books = odds.record_books(parsed, new, cons, tmp_path / "books.csv", ALIASES)
    assert len(books) == 4 and set(books["book"]) == {"draftkings", "fanduel", "bovada", "pinnacle"}
    dk = books[(books["pick_id"] == "9:1") & (books["book"] == "draftkings")].iloc[0]
    assert (dk["price_a"], dk["price_b"]) == ("1.91", "1.91")
    fd = books[(books["pick_id"] == "9:1") & (books["book"] == "fanduel")].iloc[0]
    assert (fd["price_a"], fd["price_b"]) == ("2.05", "1.8")                              # oriented to the ledger's fighter_a (Daria)
    assert odds.record_books(parsed, new, cons, tmp_path / "books.csv", ALIASES).empty    # append-only


# ---------- baseline ----------

def test_market_baseline_arithmetic(cfg):
    picks = pd.DataFrame([
        {"fighter_a": "Ann One", "fighter_b": "Bea One", "event_date": "2026-10-10", "status": "correct", "winner": "Ann One", "pick": "Ann One", "correct": "True", "p_a": "0.6", "log_loss": f"{-math.log(0.6):.4f}"},
        {"fighter_a": "Ann Two", "fighter_b": "Bea Two", "event_date": "2026-10-10", "status": "incorrect", "winner": "Bea Two", "pick": "Ann Two", "correct": "False", "p_a": "0.55", "log_loss": f"{-math.log(0.45):.4f}"},
        {"fighter_a": "Ann Three", "fighter_b": "Bea Three", "event_date": "2026-10-10", "status": "incorrect", "winner": "Ann Three", "pick": "Bea Three", "correct": "False", "p_a": "0.3", "log_loss": f"{-math.log(0.3):.4f}"},
        {"fighter_a": "Ann Four", "fighter_b": "Bea Four", "event_date": "2026-10-10", "status": "correct", "winner": "Ann Four", "pick": "Ann Four", "correct": "True", "p_a": "0.7", "log_loss": f"{-math.log(0.7):.4f}"},
        {"fighter_a": "Ann Five", "fighter_b": "Bea Five", "event_date": "2026-10-31", "status": "pending", "winner": "", "pick": "Ann Five", "correct": "", "p_a": "0.5", "log_loss": ""},
    ])
    market = pd.DataFrame([
        {"fighter_a": "Ann One", "fighter_b": "Bea One", "event_date": "2026-10-10", "snapshot_kind": "lock", "p_a_market": "0.7", "n_books": "10"},
        {"fighter_a": "Ann Two", "fighter_b": "Bea Two", "event_date": "2026-10-10", "snapshot_kind": "lock", "p_a_market": "0.4", "n_books": "8"},
        {"fighter_a": "Bea Three", "fighter_b": "Ann Three", "event_date": "2026-10-10", "snapshot_kind": "lock", "p_a_market": "0.65", "n_books": "12"},   # stored the other way round
        {"fighter_a": "Ann Five", "fighter_b": "Bea Five", "event_date": "2026-10-31", "snapshot_kind": "lock", "p_a_market": "0.52", "n_books": "3"},    # pending: not graded yet
        {"fighter_a": "Ann One", "fighter_b": "Bea One", "event_date": "2026-10-10", "snapshot_kind": "last_before_event", "p_a_market": "0.8", "n_books": "11"},
    ])
    for c in odds.LEDGER_COLUMNS:
        if c not in market.columns:
            market[c] = ""
    out = odds.market_baseline(picks, market, cfg)
    lock = out["baselines_same_bouts"]["market_devigged_lock"]
    assert lock["n"] == 3
    assert lock["accuracy"] == round(2 / 3, 3)                                    # favourite right on A1 and B2, wrong on B3
    assert lock["log_loss"] == round((-math.log(0.7) - math.log(0.6) - math.log(0.35)) / 3, 4)
    assert lock["model_accuracy_same_bouts"] == round(1 / 3, 3)
    assert lock["model_log_loss_same_bouts"] == round((-math.log(0.6) - math.log(0.45) - math.log(0.3)) / 3, 4)
    d = out["detail"]["lock"]
    assert d["agreement_rate"] == round(2 / 3, 3)
    assert d["when_model_and_market_disagree"] == {"n": 1, "model_correct": 0, "market_correct": 1}
    assert d["brier"] == round(((0.7 - 1) ** 2 + (0.4 - 0) ** 2 + (0.35 - 1) ** 2) / 3, 4)
    assert d["mean_n_books"] == 10.0
    assert out["graded_with_market"] == 3 and out["graded_without_market"] == 1
    last = out["baselines_same_bouts"]["market_devigged_last_before_event"]
    assert last["n"] == 1 and last["accuracy"] == 1.0 and last["log_loss"] == round(-math.log(0.8), 4)
    assert set(lock) == {"n", "accuracy", "log_loss", "model_accuracy_same_bouts", "model_log_loss_same_bouts"}   # drop-in shape for picks_summary.json
    assert json.dumps(out)                                                       # serialisable


def test_market_baseline_empty(cfg):
    picks = pd.DataFrame([{"fighter_a": "A", "fighter_b": "B", "event_date": "2026-10-10", "status": "correct", "winner": "A", "pick": "A", "correct": "True", "p_a": "0.6", "log_loss": "0.51"}])
    out = odds.market_baseline(picks, pd.DataFrame(columns=odds.LEDGER_COLUMNS), cfg)
    assert out["baselines_same_bouts"] == {} and out["graded_without_market"] == 1
    assert odds.market_baseline(pd.DataFrame(columns=["status"]), pd.DataFrame(columns=odds.LEDGER_COLUMNS), cfg)["graded_with_market"] == 0


# ---------- fetch (fake transport) ----------

def fake_http(status: int, events: list, remaining: str = "480"):
    calls = []

    def get(url: str, timeout: float):
        calls.append((url, timeout))
        return status, {"x-requests-remaining": remaining, "x-requests-used": "20", "x-requests-last": "3"}, json.dumps(events).encode()

    get.calls = calls
    return get


def test_fetch_upcoming_builds_request_and_reads_headers(payload, cfg, monkeypatch):
    monkeypatch.setenv(odds.ENV_KEY, "k-from-env")
    http = fake_http(200, payload)
    out = odds.fetch_upcoming(None, cfg, http=http)
    url, timeout = http.calls[0]
    assert url.startswith(f"{cfg['base_url']}/sports/{cfg['sport_key']}/odds/?") and "apiKey=k-from-env" in url
    assert "regions=" + "%2C".join(cfg["regions"]) in url and "markets=h2h" in url and "oddsFormat=decimal" in url
    assert timeout == cfg["timeout_seconds"]
    assert out["events"] == payload and out["requests_remaining"] == "480" and out["cost"] == len(cfg["regions"]) * len(cfg["markets"])
    assert "k-from-env" not in out["url"] and "apiKey=***" in out["url"]


def test_fetch_upcoming_errors(payload, cfg, monkeypatch):
    monkeypatch.delenv(odds.ENV_KEY, raising=False)
    with pytest.raises(odds.OddsError, match="ODDS_API_KEY"):
        odds.fetch_upcoming(None, cfg, http=fake_http(200, payload))
    with pytest.raises(odds.OddsError, match="max_requests_per_run"):
        odds.fetch_upcoming("k", {**cfg, "max_requests_per_run": 1, "regions": ["us", "uk", "eu"]}, http=fake_http(200, payload))
    with pytest.raises(odds.OddsError, match="HTTP 401"):
        odds.fetch_upcoming("k", cfg, http=fake_http(401, {"message": "Invalid API key"}))
    with pytest.raises(odds.OddsError, match="HTTP 429"):
        odds.fetch_upcoming("k", cfg, http=fake_http(429, {"message": "slow down"}))

    def boom(url, timeout):
        raise TimeoutError("timed out")
    with pytest.raises(odds.OddsError, match="did not answer"):
        odds.fetch_upcoming("k", cfg, http=boom)


# ---------- orchestration ----------

def test_snapshot_disabled_writes_nothing(picks, cfg, tmp_path):
    path = tmp_path / "ledger.csv"
    out = odds.snapshot(picks, FRI, cfg={**cfg, "enabled": False, "ledger": str(path)}, http=fake_http(200, []))
    assert out.empty and not path.exists()


def test_snapshot_end_to_end(payload, picks, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv(odds.ENV_KEY, "k")
    monkeypatch.setattr(odds, "_aliases", lambda: ALIASES)
    path = tmp_path / "ledger.csv"
    c = {**cfg, "ledger": str(path), "books_ledger": str(tmp_path / "books.csv")}
    new = odds.snapshot(picks, FRI, cfg=c, http=fake_http(200, payload))
    assert len(new) == 4 and sorted(set(new["snapshot_kind"])) == ["last_before_event", "lock"]
    assert (new["provider"] == c["provider"]).all() and (new["regions"] == ",".join(c["regions"])).all()
    assert not (tmp_path / "books.csv").exists()                                   # store_raw_prices is false by default
    again = odds.snapshot(picks, FRI, cfg=c, http=fake_http(200, payload))
    assert again.empty                                                             # append-only on a re-run
    offline = odds.snapshot(picks, FRI, cfg=c, http=fake_http(500, {"message": "down"}))
    assert offline.empty                                                           # network trouble never raises unless strict
    assert odds.snapshot(picks, FRI, cfg=c, http=fake_http(200, [])).empty         # out of season: no events, nothing written
    assert len(pd.read_csv(path)) == 4
    with pytest.raises(odds.OddsError):
        odds.snapshot(picks, FRI, cfg=c, http=fake_http(500, {"message": "down"}), strict=True)


def test_run_report_lists_both_kinds_of_miss(payload, picks, cfg, tmp_path, monkeypatch):
    """A pending pick within two weeks that found no market bout, and a market bout that matched no pending pick,
    are both named in the report; matched bouts and far-off picks are not."""
    monkeypatch.setenv(odds.ENV_KEY, "k")
    monkeypatch.setattr(odds, "_aliases", lambda: ALIASES)
    extra = [{"pick_id": "9:4", "fighter_a": "Nobody Known", "fighter_b": "Someone Else", "event_date": "2026-10-24", "status": "pending"}]
    p = pd.concat([picks, pd.DataFrame(extra)], ignore_index=True)
    market = payload + [{"id": "e3", "sport_key": "mma_mixed_martial_arts", "sport_title": "MMA", "commence_time": "2026-10-25T02:00:00Z",
                         "home_team": "Alexander Volkanovski", "away_team": "Movsar Evloev",
                         "bookmakers": [{"key": "bovada", "title": "Bovada", "last_update": "2026-10-20T12:00:00Z",
                                         "markets": [h2h("Alexander Volkanovski", "Movsar Evloev", 1.40, 3.00)]},
                                        {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-20T12:00:00Z",
                                         "markets": [h2h("Alexander Volkanovski", "Movsar Evloev", 1.45, 2.90)]}]}]
    c = {**cfg, "ledger": str(tmp_path / "ledger.csv"), "run_report": str(tmp_path / "run.json")}
    odds.snapshot(p, FRI, cfg=c, http=fake_http(200, market))
    rep = json.loads((tmp_path / "run.json").read_text())
    assert rep["bouts_from_api"] == 3 and rep["matched_to_pending_picks"] == 2
    assert rep["unmatched_pending_picks"] == ["Nobody Known vs Someone Else (2026-10-24)"]       # 9:3 is five weeks out: not listed
    assert rep["unmatched_market_bouts"] == ["Alexander Volkanovski vs Movsar Evloev (2026-10-25, 2 books)"]
    assert "credits_remaining" in rep and rep["horizon_days"] == 14
