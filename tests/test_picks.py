"""Tests for src/mmalab/picks.py: the schedule feed parser and its schema check, the no-pick band at lock time,
grading of a no-pick row, the cumulative record and its SVG chart. Everything runs offline on fixtures and
temporary files; the real ledger, config and outputs are never read or written."""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pandas as pd
import pytest

from mmalab import picks

CFG = {
    "source": "https://example.invalid/scoreboard", "horizon_days": 21, "void_after_days": 10, "match_window_days": 3,
    "provisional_max_bouts": 3, "exclude_events": ["Contender Series", "Road to UFC"], "publish_page": False,
    "confidence_bands": [0.5, 0.55, 0.6, 0.65, 0.7, 1.0], "no_pick_band": 0.02, "no_pick_since": date(2026, 10, 20),
}
SVG_NS = "{http://www.w3.org/2000/svg}"


# ---------- fixtures in the feed's shape ----------

def competitor(cid: str, name: str, order: int) -> dict:
    return {"id": cid, "uid": f"s:3301~a:{cid}", "type": "athlete", "order": order, "winner": False,
            "athlete": {"fullName": name, "displayName": name, "shortName": name}}


def competition(cid: str, when: str, weight: str, names: list[str], periods: int = 3, state: str = "pre", completed: bool = False) -> dict:
    return {"id": cid, "uid": f"s:3301~l:3321~c:{cid}", "date": when, "type": {"id": "1", "abbreviation": weight},
            "competitors": [competitor(f"{cid}{i}", n, i + 1) for i, n in enumerate(names)],
            "status": {"clock": 0.0, "period": 0, "type": {"id": "1", "name": "STATUS_SCHEDULED", "state": state, "completed": completed}},
            "format": {"regulation": {"periods": periods}}}


def feed_fixture(when: str = "2026-11-14T22:00Z") -> dict:
    """One upcoming UFC card with the cases the parser must handle, a Contender Series card it must exclude and a
    card already in the past, wrapped the way ESPN's scoreboard returns them."""
    card = {"id": "600070001", "uid": "s:3301~l:3321~e:600070001", "date": when, "name": "UFC 334: Alpha vs. Bravo", "shortName": "UFC 334",
            "competitions": [
                competition("401950001", when, "Lightweight", ["Alpha Able", "Bravo Baker"], periods=5),
                competition("401950002", when, "W Strawweight", ["Carla Cruz", "Dana Diaz"]),
                competition("401950003", when, "Welterweight", ["Evan Ellis", "TBA"]),                                   # unfilled slot
                competition("401950004", when, "Flyweight", ["Finn Ford", "Gus Grant"], state="post", completed=True),  # already fought
                competition("401950005", when, "Heavyweight", ["Ivan Ice", "Hank Hill"]),
            ]}
    card["competitions"][4]["competitors"].reverse()   # listed out of order: the 'order' field decides who is fighter_a
    series = {"id": "600070002", "date": "2026-11-10T23:00Z", "name": "Dana White's Contender Series: Week 10",
              "competitions": [competition("401950010", "2026-11-10T23:00Z", "Bantamweight", ["Jay Jones", "Kim Kay"])]}
    past = {"id": "600070003", "date": "2026-10-10T20:00Z", "name": "UFC Fight Night: Past vs. Card",
            "competitions": [competition("401950020", "2026-10-10T20:00Z", "Featherweight", ["Lee Long", "Max Mann"])]}
    return {"leagues": [], "season": {"year": 2026, "type": 2}, "day": {"date": "2026-10-20"}, "events": [card, series, past]}


def ledger_row(**kw) -> dict:
    row = {c: "" for c in picks.COLUMNS}
    row.update({"model": "performance-adjusted Elo v1.0 (tuned_params)", "status": "pending", "rounds": "3", "provisional": "False",
                "matched_a": "True", "matched_b": "True", "predicted_at_utc": "2026-10-20T12:00:00Z", "data_through": "2026-10-17"})
    row.update({k: str(v) for k, v in kw.items()})
    return row


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(picks, "_cfg", lambda: dict(CFG))
    return dict(CFG)


@pytest.fixture
def sandbox(tmp_path, monkeypatch, cfg):
    """Point every path the module writes or reads at a temporary directory."""
    (tmp_path / "out").mkdir()
    (tmp_path / "pred").mkdir()
    monkeypatch.setattr(picks, "PROC", tmp_path)
    monkeypatch.setattr(picks, "OUT", tmp_path / "out")
    monkeypatch.setattr(picks, "PRED", tmp_path / "pred")
    monkeypatch.setattr(picks, "LEDGER", tmp_path / "pred" / "picks.csv")
    monkeypatch.setattr(picks, "UNMATCHED", tmp_path / "pred" / "unmatched_names.csv")
    return tmp_path


# ---------- parse ----------

def test_parse_upcoming_reads_scheduled_bouts(cfg):
    up = picks.parse_upcoming(feed_fixture(), pd.Timestamp("2026-10-17"))
    assert list(up["espn_name_a"]) == ["Alpha Able", "Carla Cruz", "Ivan Ice"]
    assert list(up["espn_name_b"]) == ["Bravo Baker", "Dana Diaz", "Hank Hill"]
    assert list(up["division"]) == ["Lightweight", "Women's Strawweight", "Heavyweight"]
    assert list(up["rounds"]) == [5, 3, 3]
    assert set(up["event"]) == {"UFC 334: Alpha vs. Bravo"}
    assert list(up["event_id"]) == ["600070001"] * 3
    assert list(up["competition_id"]) == ["401950001", "401950002", "401950005"]
    assert [str(d) for d in up["event_date"]] == ["2026-11-14"] * 3


def test_parse_upcoming_skips_cards_already_in_the_data(cfg):
    assert picks.parse_upcoming(feed_fixture(), pd.Timestamp("2026-11-14")).empty
    assert picks.parse_upcoming({"events": []}, pd.Timestamp("2026-10-17")).empty


# ---------- validate_feed ----------

def test_validate_feed_accepts_a_good_payload():
    assert picks.validate_feed(feed_fixture()) == []
    saved_copy = {"fetched_at_utc": "2026-10-19T18:56:26Z", "url": "https://example.invalid", "events": feed_fixture()["events"]}
    assert picks.validate_feed(saved_copy) == []
    if picks.RAW.exists():   # the saved copy of the real feed, when the checkout has one
        assert picks.validate_feed(json.loads(picks.RAW.read_text())) == []


def test_validate_feed_reports_a_broken_payload():
    assert picks.validate_feed(None) == ["payload is not a JSON object"]
    assert picks.validate_feed([]) == ["payload is not a JSON object"]
    assert picks.validate_feed({"schedule": []}) == ["'events' is missing or not a list"]
    assert picks.validate_feed({"events": {}}) == ["'events' is missing or not a list"]

    bad = feed_fixture()
    card = bad["events"][0]
    del card["date"]                                                        # event without a date
    card["competitions"][0].pop("competitors")                              # bout without competitors
    card["competitions"][1]["competitors"][0]["athlete"] = {"id": "x"}      # scheduled bout, athlete without a name
    card["competitions"][4]["type"] = {}                                    # no weight class
    card["competitions"][4]["format"] = None                                # no scheduled rounds
    card["competitions"][3]["competitors"][1].pop("athlete")                # finished bout: not held to the per-bout checks
    card["competitions"][2]["competitors"].pop()                            # one competitor left: not a bout the parser locks
    bad["events"][2] = "not an event"
    problems = picks.validate_feed(bad)
    assert problems == [
        "events[0].date: missing or not an ISO date",
        "events[0].competitions[0].competitors: missing or not a list",
        "events[0].competitions[1].competitors[0].athlete: no displayName or fullName",
        "events[0].competitions[4].type: no weight class (abbreviation or text)",
        "events[0].competitions[4].format.regulation.periods: missing",
        "events[2]: not an object",
    ]
    assert not any("competitions[2]" in p or "competitions[3]" in p for p in problems)

    renamed = feed_fixture()
    renamed["events"][0]["date"] = "Saturday 14 November"
    assert picks.validate_feed(renamed) == ["events[0].date: 'Saturday 14 November' is not an ISO date"]


def test_validate_feed_caps_the_problem_list():
    flood = {"events": [{"id": str(i), "name": "UFC", "competitions": []} for i in range(50)]}   # every event lacks a date
    problems = picks.validate_feed(flood)
    assert len(problems) == picks.MAX_FEED_PROBLEMS + 1
    assert problems[-1] == f"... and {50 - picks.MAX_FEED_PROBLEMS} more"


# ---------- the no-pick band ----------

def test_no_pick_rule_at_the_band_edge():
    band = CFG["no_pick_band"]
    assert picks.choose_pick(0.52, "A", "B", band) == "A"          # on the edge: still a pick
    assert picks.choose_pick(0.48, "A", "B", band) == "B"
    assert picks.choose_pick(0.5199, "A", "B", band) == picks.NO_PICK
    assert picks.choose_pick(0.4801, "A", "B", band) == picks.NO_PICK
    assert picks.choose_pick(0.5, "A", "B", band) == picks.NO_PICK
    assert picks.choose_pick(0.5, "A", "B", None) == "A"            # rule not in force: the original behaviour
    assert picks.choose_pick(0.4999, "A", "B", None) == "B"
    assert picks.choose_pick(0.5, "A", "B", 0.0) == "A"             # a zero band is the same as none


def test_no_pick_band_applies_from_no_pick_since():
    assert picks.no_pick_band_for(CFG, date(2026, 10, 19)) is None
    assert picks.no_pick_band_for(CFG, date(2026, 10, 20)) == 0.02
    assert picks.no_pick_band_for({**CFG, "no_pick_since": "2026-10-20"}, date(2026, 11, 1)) == 0.02
    assert picks.no_pick_band_for({k: v for k, v in CFG.items() if k != "no_pick_band"}, date(2026, 12, 1)) is None
    assert picks.no_pick_band_for({k: v for k, v in CFG.items() if k != "no_pick_since"}, date(2026, 12, 1)) is None


class FakeShadow:
    """Stands in for the shadow model so lock() runs without the rating files."""
    ok = True
    probs = {("Alpha Able", "Bravo Baker"): 0.70, ("Carla Cruz", "Dana Diaz"): 0.505, ("Ivan Ice", "Hank Hill"): 0.40}

    def prob(self, a, b, event_date, rounds):
        return self.probs[(a, b)]


def test_lock_records_no_pick_for_a_coin_flip(sandbox, monkeypatch):
    pd.DataFrame([{"date": "2026-06-01", "fighter_a": "Alpha Able", "fighter_b": "Bravo Baker", "result_a": 1.0},
                  {"date": "2026-07-01", "fighter_a": "Ivan Ice", "fighter_b": "Zed Zorn", "result_a": 1.0}]).to_csv(sandbox / "bouts.csv", index=False)
    (sandbox / "out" / "backtest_report.json").write_text("{}")
    (sandbox / "out" / "freeze_hash.txt").write_text("abc123 tree\n")
    tuned = {"Alpha Able": 1600.0, "Bravo Baker": 1500.0, "Ivan Ice": 1650.0}
    monkeypatch.setattr(picks, "_ratings", lambda: (tuned, dict(tuned)))
    monkeypatch.setattr(picks, "_real_scores", lambda: {})
    monkeypatch.setattr(picks, "_aliases", lambda: {})
    monkeypatch.setattr(picks, "Shadow", FakeShadow)
    when = (date.today() + timedelta(days=7)).strftime("%Y-%m-%dT22:00Z")
    upcoming = picks.parse_upcoming(feed_fixture(when), pd.Timestamp("2026-10-17"))

    ledger = picks.lock(upcoming, pd.Timestamp("2026-10-17")).set_index("pick_id")
    assert len(ledger) == 3 and set(ledger["status"]) == {"pending"}
    flip = ledger.loc["600070001:401950002"]              # two names outside UFCStats: 1500 against 1500
    assert (flip["pick"], flip["confidence"], flip["p_a"], flip["p_pick"]) == (picks.NO_PICK, picks.NO_PICK_BAND, "0.5", "0.5")
    assert flip["pick_v11"] == picks.NO_PICK and flip["p_a_v11"] == "0.505"
    assert flip["matched_a"] == "False" and flip["provisional"] == "True" and flip["note"].startswith("name not in UFCStats history")
    fav = ledger.loc["600070001:401950001"]
    assert (fav["pick"], fav["confidence"], fav["p_a"], fav["pick_v11"]) == ("Alpha Able", "60%-65%", "0.6401", "Alpha Able")
    dog = ledger.loc["600070001:401950005"]
    assert (dog["pick"], dog["confidence"], dog["pick_v11"]) == ("Ivan Ice", "70%+", "Hank Hill")
    on_disk = pd.read_csv(sandbox / "pred" / "picks.csv", dtype=str, keep_default_na=False)
    assert list(on_disk.columns) == picks.COLUMNS and len(on_disk) == 3

    # the same bouts locked while the rule is not yet in force keep the original tie-break to fighter_a
    monkeypatch.setattr(picks, "_cfg", lambda: {**CFG, "no_pick_since": date(2099, 1, 1)})
    monkeypatch.setattr(picks, "LEDGER", sandbox / "pred" / "picks_before.csv")
    before = picks.lock(upcoming, pd.Timestamp("2026-10-17")).set_index("pick_id").loc["600070001:401950002"]
    assert (before["pick"], before["confidence"], before["pick_v11"]) == ("Carla Cruz", "50%-55%", "Carla Cruz")


# ---------- grading and the summary ----------

def graded_fixture(sandbox) -> pd.DataFrame:
    pd.DataFrame([
        {"date": "2026-10-10", "fighter_a": "Alpha Able", "fighter_b": "Bravo Baker", "result_a": 1.0, "method": "KO/TKO", "bout_url": "u1"},
        {"date": "2026-10-10", "fighter_a": "Carla Cruz", "fighter_b": "Dana Diaz", "result_a": 0.0, "method": "U-DEC", "bout_url": "u2"},
        {"date": "2026-10-10", "fighter_a": "Evan Ellis", "fighter_b": "Finn Ford", "result_a": 0.5, "method": "M-DEC", "bout_url": "u3"},
        {"date": "2026-10-10", "fighter_a": "Gus Grant", "fighter_b": "Hank Hill", "result_a": 1.0, "method": "SUB", "bout_url": "u4"},
    ]).to_csv(sandbox / "bouts.csv", index=False)
    ledger = pd.DataFrame([
        ledger_row(pick_id="e:1", event="UFC Test", event_date="2026-10-10", fighter_a="Alpha Able", fighter_b="Bravo Baker",
                   p_a="0.51", pick=picks.NO_PICK, p_pick="0.51", confidence=picks.NO_PICK_BAND, p_a_v11="0.61", pick_v11="Alpha Able"),
        ledger_row(pick_id="e:2", event="UFC Test", event_date="2026-10-10", fighter_a="Carla Cruz", fighter_b="Dana Diaz",
                   p_a="0.6", pick="Carla Cruz", p_pick="0.6", confidence="60%-65%", p_a_v11="0.49", pick_v11=picks.NO_PICK),
        ledger_row(pick_id="e:3", event="UFC Test", event_date="2026-10-10", fighter_a="Evan Ellis", fighter_b="Finn Ford",
                   p_a="0.495", pick=picks.NO_PICK, p_pick="0.505", confidence=picks.NO_PICK_BAND,
                   matched_b="False", note="name not in UFCStats history; treated as a debut at 1500"),
        ledger_row(pick_id="e:4", event="UFC Test", event_date="2026-10-10", fighter_a="Gus Grant", fighter_b="Hank Hill",
                   p_a="0.58", pick="Gus Grant", p_pick="0.58", confidence="55%-60%", p_a_v11="0.45", pick_v11="Hank Hill"),
        ledger_row(pick_id="e:5", event="UFC Later", event_date="2026-12-05", fighter_a="Lee Long", fighter_b="Max Mann",
                   p_a="0.5", pick=picks.NO_PICK, p_pick="0.5", confidence=picks.NO_PICK_BAND),
    ], columns=picks.COLUMNS)
    return picks.grade(ledger, pd.Timestamp("2026-10-17"))


def test_grade_marks_a_no_pick_row_without_scoring_it(sandbox):
    g = graded_fixture(sandbox).set_index("pick_id")
    assert g.loc["e:1", "status"] == "no pick" and g.loc["e:1", "winner"] == "Alpha Able"
    assert g.loc["e:1", ["correct", "log_loss", "brier"]].tolist() == ["", "", ""]
    assert g.loc["e:1", ["result_date", "method", "bout_url", "first_listed_matches"]].tolist() == ["2026-10-10", "KO/TKO", "u1", "True"]
    assert g.loc["e:1", "graded_at_utc"].endswith("Z") and g.loc["e:1", "note"] == "no pick: p_a inside the no-pick band at lock time"
    assert g.loc["e:2", "status"] == "incorrect" and g.loc["e:2", "winner"] == "Dana Diaz" and g.loc["e:2", "correct"] == "False"
    assert float(g.loc["e:2", "log_loss"]) == pytest.approx(-math.log(0.4), abs=1e-3)
    assert g.loc["e:3", "status"] == "no pick" and g.loc["e:3", "winner"] == ""
    assert g.loc["e:3", "note"] == "name not in UFCStats history; treated as a debut at 1500; no pick: p_a inside the no-pick band at lock time; draw or no contest"
    assert g.loc["e:4", "status"] == "correct" and g.loc["e:4", "correct"] == "True"
    assert g.loc["e:5", "status"] == "pending"
    assert (sandbox / "pred" / "picks.csv").exists()


def test_summarize_counts_no_picks_apart_from_the_record(sandbox):
    graded = graded_fixture(sandbox)
    s = picks.summarize(graded, {"ok": True, "checked_at_utc": "2026-10-20T12:00:00Z"})
    assert (s["graded"], s["no_pick"], s["pending"], s["void"]) == (2, 2, 1, 0)
    assert s["feed_status"] == {"ok": True, "checked_at_utc": "2026-10-20T12:00:00Z"}
    assert s["record"]["correct"] == 1 and s["record"]["incorrect"] == 1 and s["record"]["accuracy"] == 0.5
    assert s["record"]["accuracy_wilson95"] == picks._wilson(1, 2)
    assert [b["band"] for b in s["by_confidence"]] == ["55%-60%", "60%-65%"]       # no "no pick" band in the calibration table
    assert s["by_event"] == [{"event": "UFC Test", "date": "2026-10-10", "n": 2, "correct": 1, "no_pick": 2, "log_loss": s["by_event"][0]["log_loss"]}]
    shadow = s["baselines_same_bouts"]["shadow_v11"]
    assert shadow["n"] == 1 and shadow["accuracy"] == 0.0 and shadow["no_pick"] == 1    # abstained on e:2, scored on e:4 only
    assert s["upcoming"] == [{"event": "UFC Later", "date": "2026-12-05", "picks": 0, "no_pick": 1, "locked_at_utc": "2026-10-20T12:00:00Z"}]
    written = json.loads((sandbox / "out" / "picks_summary.json").read_text())
    assert written["no_pick"] == 2 and written["feed_status"]["ok"] is True
    assert "feed_status" not in picks.summarize(graded)

    broken = picks.summarize(graded, {"ok": False, "problems": ["events[0].date: missing or not an ISO date"], "checked_at_utc": "x"})
    assert broken["feed_status"]["ok"] is False and broken["feed_status"]["problems"] == ["events[0].date: missing or not an ISO date"]


def test_summarize_with_nothing_graded(sandbox):
    ledger = pd.DataFrame([ledger_row(pick_id="e:9", event="UFC Later", event_date="2026-12-05", pick="A", fighter_a="A", fighter_b="B")], columns=picks.COLUMNS)
    s = picks.summarize(ledger)
    assert (s["graded"], s["no_pick"], s["pending"]) == (0, 0, 1) and "record" not in s
    assert s["upcoming"][0]["picks"] == 1 and s["upcoming"][0]["no_pick"] == 0


# ---------- cumulative record and chart ----------

def synthetic_ledger() -> pd.DataFrame:
    """Five resolved bouts whose grading order differs from ledger order, plus a pending one."""
    rows = [
        ("e:1", "correct", "A1", "A1", "2026-10-12T10:00:00Z", "2026-10-10", "A1"),
        ("e:2", "incorrect", "B2", "A2", "2026-10-12T10:00:00Z", "2026-10-10", "A2"),
        ("e:3", "correct", "A3", "A3", "2026-10-05T10:00:00Z", "2026-10-03", picks.NO_PICK),   # graded first; shadow abstained
        ("e:4", "no pick", picks.NO_PICK, "A4", "2026-10-19T10:00:00Z", "2026-10-17", "B4"),   # v1.0 abstained; shadow missed
        ("e:5", "incorrect", "A5", "B5", "2026-10-19T10:00:00Z", "2026-10-17", "B5"),
        ("e:6", "pending", "A6", "", "", "", "A6"),
    ]
    return pd.DataFrame([ledger_row(pick_id=pid, status=st, pick=pick, winner=win, graded_at_utc=at, result_date=rd, event_date=rd or "2026-12-05",
                                    fighter_a=pid.replace("e:", "A"), fighter_b=pid.replace("e:", "B"), p_a="0.55", p_a_v11="0.55", pick_v11=p11,
                                    correct=str(st == "correct") if st in ("correct", "incorrect") else "")
                         for pid, st, pick, win, at, rd, p11 in rows], columns=picks.COLUMNS)


def test_cumulative_series_follows_grading_order_with_wilson_bounds():
    s = picks.cumulative_series(synthetic_ledger())
    v10, v11 = s["v10"], s["v11"]
    assert [p["pick_id"] for p in v10] == ["e:3", "e:1", "e:2", "e:5"]
    assert [(p["n"], p["correct"]) for p in v10] == [(1, 1), (2, 2), (3, 2), (4, 2)]
    assert [p["accuracy"] for p in v10] == [1.0, 1.0, 0.6667, 0.5]
    for p in v10 + v11:
        lo, hi = p["wilson95"]
        assert p["wilson95"] == picks._wilson(p["correct"], p["n"])
        assert 0.0 <= lo <= p["accuracy"] <= hi <= 1.0
    assert v10[0]["wilson95"] == [0.207, 1.0]
    assert v10[-1]["wilson95"] == [0.15, 0.85]
    assert v10[-1]["event_date"] == "2026-10-17" and v10[-1]["graded_at_utc"] == "2026-10-19T10:00:00Z"
    # the shadow skips e:3 (it abstained) and counts e:4 (v1.0 abstained, the shadow picked B4 and lost); it had e:2 and e:5 right
    assert [p["pick_id"] for p in v11] == ["e:1", "e:2", "e:4", "e:5"]
    assert [(p["n"], p["correct"]) for p in v11] == [(1, 1), (2, 2), (3, 2), (4, 3)]
    assert picks.cumulative_series(pd.DataFrame(columns=picks.COLUMNS)) == {"v10": [], "v11": []}
    only_pending = synthetic_ledger().query("status == 'pending'")
    assert picks.cumulative_series(only_pending) == {"v10": [], "v11": []}


def test_cumulative_chart_svg_is_well_formed():
    svg = picks.cumulative_chart_svg(picks.cumulative_series(synthetic_ledger()))
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    root = ET.fromstring(svg)
    assert root.tag == f"{SVG_NS}svg" and root.get("viewBox") == "0 0 340 232"
    assert len(root.findall(f"{SVG_NS}polyline")) == 2                    # v1.0 line and the dashed shadow line
    assert len(root.findall(f"{SVG_NS}polygon")) == 1                     # the Wilson band
    dashed = [e for e in root.findall(f"{SVG_NS}polyline") if e.get("stroke-dasharray")]
    assert len(dashed) == 1 and float(dashed[0].get("stroke-width")) < float([e for e in root.findall(f"{SVG_NS}polyline") if e not in dashed][0].get("stroke-width"))
    assert any(e.get("stroke-dasharray") == "2 3" for e in root.findall(f"{SVG_NS}line"))   # the dotted 50% reference
    texts = [t.text for t in root.iter(f"{SVG_NS}text")]
    assert "v1.0 pick: 2 of 4 correct (50.0%)" in texts and "Shadow v1.1: 3 of 4 correct (75.0%)" in texts
    assert {"0%", "25%", "50%", "75%", "100%"} <= set(texts) and "Accuracy" in texts
    assert "<script" not in svg and "http://" not in svg.replace("http://www.w3.org/2000/svg", "")


def test_cumulative_chart_svg_empty_state_and_single_series():
    empty = picks.cumulative_chart_svg({"v10": [], "v11": []})
    assert empty.startswith("<svg") and "No graded picks yet" in empty
    root = ET.fromstring(empty)
    assert not root.findall(f"{SVG_NS}polyline") and not root.findall(f"{SVG_NS}polygon")
    assert ET.fromstring(picks.cumulative_chart_svg({})).tag == f"{SVG_NS}svg"

    series = picks.cumulative_series(synthetic_ledger())
    one = picks.cumulative_chart_svg({"v10": series["v10"][:1], "v11": []})
    root = ET.fromstring(one)
    assert len(root.findall(f"{SVG_NS}polyline")) == 1 and not root.findall(f"{SVG_NS}polygon")
    assert "Shadow v1.1" not in one and "100.0%" in one
