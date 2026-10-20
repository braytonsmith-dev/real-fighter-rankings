"""
Same-name fighters (config/fighter_disambiguation.yaml, data finding D8): on a synthetic shared name,
bouts go to the right fighter by division and by explicit bout URL, the names reach bouts, round stats
and the tale of the tape, and an unsettled case (a bout no entry claims, a shared name with no entry)
stops ingest instead of merging two careers. The last tests check the repository file against the
repository data.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mmalab import ingest
from mmalab.ingest import DisambiguationError

U1 = "http://ufcstats.com/fighter-details/aaaaaaaaaaaaaaa1"     # the lightweight Sam Doe (keeps the plain name)
U2 = "http://ufcstats.com/fighter-details/bbbbbbbbbbbbbbb2"     # the heavyweight Sam Doe
U3 = "http://ufcstats.com/fighter-details/ccccccccccccccc3"     # an unrelated fighter
B_LW, B_HW, B_CATCH, B_OTHER = (f"http://ufcstats.com/fight-details/{i:016d}" for i in range(1, 5))


@pytest.fixture
def toy_tott() -> pd.DataFrame:
    return pd.DataFrame({
        "FIGHTER": ["Sam Doe", "Sam Doe", "Pat Roe", "Lee Poe"],
        "HEIGHT": ["5' 9\"", "6' 4\"", "5' 11\"", "6' 0\""],
        "WEIGHT": ["155 lbs.", "250 lbs.", "155 lbs.", "250 lbs."],
        "REACH": ["70\"", "80\"", "--", "78\""],
        "STANCE": ["Orthodox", "Southpaw", None, "Orthodox"],
        "DOB": ["Jan 02, 1990", "Mar 04, 1985", "May 06, 1992", "--"],
        "URL": [U1, U2, U3, "http://ufcstats.com/fighter-details/ddddddddddddddd4"],
    })


@pytest.fixture
def toy_details(toy_tott: pd.DataFrame) -> pd.DataFrame:
    first_last = toy_tott["FIGHTER"].str.split(" ", n=1, expand=True)
    return pd.DataFrame({"FIRST": first_last[0], "LAST": first_last[1], "NICKNAME": [None, "Tall", None, None], "URL": toy_tott["URL"]})


@pytest.fixture
def toy_bouts() -> pd.DataFrame:
    """Three bouts of the shared name (lightweight, heavyweight, catch weight) and one unrelated bout.
    The heavyweight bout sits under an event the round stats spell differently (ingest.EVENT_ALIASES)."""
    return pd.DataFrame({
        "event": ["UFC 1000", "Noche UFC: Lopes vs. Silva", "UFC 1001", "UFC 1001"],
        "date": pd.to_datetime(["2025-01-11", "2025-02-08", "2025-03-15", "2025-03-15"]),
        "division": ["Lightweight", "Heavyweight", "Catch Weight", "Heavyweight"],
        "fighter_a": ["Sam Doe", "Lee Poe", "Pat Roe", "Lee Poe"],
        "fighter_b": ["Pat Roe", "Sam Doe", "Sam Doe", "Pat Roe"],
        "result_a": [1.0, 0.0, 0.5, 1.0],
        "bout_url": [B_LW, B_HW, B_CATCH, B_OTHER],
        "bout_id": [0, 1, 2, 3],
    })


@pytest.fixture
def toy_rounds() -> pd.DataFrame:
    rows = [("UFC 1000", "Sam Doe vs. Pat Roe", "Sam Doe", 1), ("UFC 1000", "Sam Doe vs. Pat Roe", "Pat Roe", 1),
            ("UFC Fight Night: Lopes vs. Silva", "Lee Poe vs. Sam Doe", "Lee Poe", 1),
            ("UFC Fight Night: Lopes vs. Silva", "Lee Poe vs. Sam Doe", "Sam Doe", 1),
            ("UFC 1001", "Pat Roe vs. Sam Doe", "Pat Roe", 1), ("UFC 1001", "Pat Roe vs. Sam Doe", "Sam Doe", 1),
            ("UFC 1001", "Lee Poe vs. Pat Roe", "Lee Poe", 1), ("UFC 1001", "Lee Poe vs. Pat Roe", "Pat Roe", 1)]
    df = pd.DataFrame(rows, columns=["event", "bout", "fighter", "round"])
    df["sig_landed"] = range(len(df))
    return df


def config(catch_to: str | None = None) -> dict:
    """The lightweight keeps the plain name and takes Lightweight; the heavyweight takes Heavyweight and,
    when `catch_to` names him, the catch-weight bout by its URL."""
    cfg = {"Sam Doe": [
        {"url": U1, "name": "Sam Doe", "divisions": ["Lightweight"], "bout_urls": []},
        {"url": U2, "name": "Sam Doe (Tall)", "divisions": ["Heavyweight"], "bout_urls": []},
    ]}
    if catch_to:
        next(e for e in cfg["Sam Doe"] if e["name"] == catch_to)["bout_urls"].append(B_CATCH)
    return cfg


def test_shared_names_are_detected_from_both_fighter_files(toy_tott, toy_details):
    assert ingest.shared_display_names(toy_tott, toy_details) == {"Sam Doe": {U1, U2}}
    assert ingest.shared_display_names(toy_tott.iloc[[0, 2, 3]], toy_details) == {"Sam Doe": {U1, U2}}   # details alone still finds it
    assert ingest.shared_display_names(toy_tott.iloc[[0, 2, 3]], None) == {}


def test_assignment_by_division_reaches_bouts_rounds_and_fighters(toy_bouts, toy_rounds, toy_tott, toy_details):
    b, r, names_by_url, assigned = ingest.disambiguate(toy_bouts, toy_rounds, toy_tott, toy_details, config(catch_to="Sam Doe"))
    assert b.set_index("bout_url").loc[B_LW, "fighter_a"] == "Sam Doe"
    assert b.set_index("bout_url").loc[B_HW, "fighter_b"] == "Sam Doe (Tall)"
    # everything else is untouched: other rows and every non-name column
    other = [c for c in toy_bouts.columns if c not in ("fighter_a", "fighter_b")]
    assert b[other].equals(toy_bouts[other])
    assert b.set_index("bout_url").loc[B_OTHER, ["fighter_a", "fighter_b"]].tolist() == ["Lee Poe", "Pat Roe"]
    # round stats: the fighter column and the bout label, under the event spelling the stats file uses
    hw = r[r["event"] == "UFC Fight Night: Lopes vs. Silva"]
    assert hw["bout"].unique().tolist() == ["Lee Poe vs. Sam Doe (Tall)"]
    assert sorted(hw["fighter"]) == ["Lee Poe", "Sam Doe (Tall)"]
    assert r.loc[r["event"] == "UFC 1000", "bout"].unique().tolist() == ["Sam Doe vs. Pat Roe"]
    kept = [c for c in toy_rounds.columns if c not in ("fighter", "bout")]
    assert r[kept].equals(toy_rounds[kept])
    # the tale of the tape gets one row per fighter page, named by the config
    f = ingest.build_fighters(toy_tott, names_by_url)
    assert len(f) == 4 and f["fighter"].is_unique
    assert f.set_index("fighter_url").loc[U2, "fighter"] == "Sam Doe (Tall)"
    assert f.set_index("fighter_url").loc[U2, "height_in"] == 76
    assert f.set_index("fighter_url").loc[U1, "fighter"] == "Sam Doe"
    assert len(assigned) == 3 and set(assigned["old"]) == {"Sam Doe"}


def test_explicit_bout_url_wins_over_division(toy_bouts, toy_rounds, toy_tott, toy_details):
    b, r, _, assigned = ingest.disambiguate(toy_bouts, toy_rounds, toy_tott, toy_details, config(catch_to="Sam Doe (Tall)"))
    assert b.set_index("bout_url").loc[B_CATCH, "fighter_b"] == "Sam Doe (Tall)"
    assert b.set_index("bout_url").loc[B_LW, "fighter_a"] == "Sam Doe"           # divisions still settle the rest
    catch = r[(r["event"] == "UFC 1001") & (r["bout"].str.startswith("Pat Roe"))]
    assert catch["bout"].unique().tolist() == ["Pat Roe vs. Sam Doe (Tall)"]
    assert sorted(catch["fighter"]) == ["Pat Roe", "Sam Doe (Tall)"]
    assert dict(zip(assigned["bout_url"], assigned["new"]))[B_CATCH] == "Sam Doe (Tall)"


def test_unclaimed_bout_stops_ingest(toy_bouts, toy_rounds, toy_tott, toy_details):
    # the catch-weight bout is in neither entry's divisions and in no bout_urls
    with pytest.raises(DisambiguationError, match=f"Sam Doe.*claimed by no entry(.|\n)*{B_CATCH}"):
        ingest.disambiguate(toy_bouts, toy_rounds, toy_tott, toy_details, config())


def test_shared_name_missing_from_config_stops_ingest(toy_bouts, toy_rounds, toy_tott, toy_details):
    with pytest.raises(DisambiguationError, match="no entry.*Sam Doe"):
        ingest.disambiguate(toy_bouts, toy_rounds, toy_tott, toy_details, {})


def test_config_urls_must_match_the_fighter_files(toy_bouts, toy_rounds, toy_tott, toy_details):
    cfg = config(catch_to="Sam Doe")
    cfg["Sam Doe"][1]["url"] = "http://ufcstats.com/fighter-details/0000000000000000"
    with pytest.raises(DisambiguationError, match="URLs differ"):
        ingest.disambiguate(toy_bouts, toy_rounds, toy_tott, toy_details, cfg)
    stale = {**config(catch_to="Sam Doe"), "Pat Roe": [
        {"url": U3, "name": "Pat Roe", "divisions": [], "bout_urls": []},
        {"url": "http://ufcstats.com/fighter-details/0000000000000000", "name": "Pat Roe (x)", "divisions": [], "bout_urls": []}]}
    with pytest.raises(DisambiguationError, match="no longer share: Pat Roe"):
        ingest.disambiguate(toy_bouts, toy_rounds, toy_tott, toy_details, stale)


def test_suffixed_name_may_not_belong_to_another_fighter(toy_bouts, toy_rounds, toy_tott, toy_details):
    cfg = config(catch_to="Sam Doe")
    cfg["Sam Doe"][1]["name"] = "Pat Roe"
    with pytest.raises(DisambiguationError, match="already belongs"):
        ingest.disambiguate(toy_bouts, toy_rounds, toy_tott, toy_details, cfg)


def test_round_stats_of_a_shared_name_without_a_bout_stop_ingest(toy_bouts, toy_rounds, toy_tott, toy_details):
    orphan = pd.DataFrame([{"event": "UFC 999", "bout": "Sam Doe vs. Nobody", "fighter": "Sam Doe", "round": 1, "sig_landed": 0}])
    with pytest.raises(DisambiguationError, match="UFC 999"):
        ingest.disambiguate(toy_bouts, pd.concat([toy_rounds, orphan], ignore_index=True), toy_tott, toy_details, config(catch_to="Sam Doe"))


@pytest.mark.parametrize("text, message", [
    ("Sam Doe:\n  - {url: u1, name: Sam Doe, divisions: [Lightweight]}\n", "at least two entries"),
    ("Sam Doe:\n  - {url: u1, name: Sam Doe (A), divisions: []}\n  - {url: u2, name: Sam Doe (B), divisions: []}\n", "keep the plain name"),
    ("Sam Doe:\n  - {url: u1, name: Sam Doe, divisions: []}\n  - {url: u2, name: Samuel Doe, divisions: []}\n", "suffix in parentheses"),
    ("Sam Doe:\n  - {url: u1, name: Sam Doe, divisions: [Lightweight]}\n  - {url: u2, name: Sam Doe (B), divisions: [Lightweight]}\n", "claims 'Lightweight' for both"),
    ("Sam Doe:\n  - {url: u1, name: Sam Doe, divisions: [Fly weight]}\n  - {url: u2, name: Sam Doe (B), divisions: []}\n", "unknown divisions"),
    ("Sam Doe:\n  - {url: u1, name: Sam Doe, divisions: []}\n  - {url: u1, name: Sam Doe (B), divisions: []}\n", "URL twice"),
])
def test_load_disambiguation_rejects_malformed_files(tmp_path: Path, text: str, message: str):
    p = tmp_path / "fighter_disambiguation.yaml"
    p.write_text(text)
    with pytest.raises(DisambiguationError, match=message):
        ingest.load_disambiguation(p)


def test_load_disambiguation_accepts_a_minimal_file_and_a_missing_one(tmp_path: Path):
    p = tmp_path / "fighter_disambiguation.yaml"
    p.write_text("Sam Doe:\n  - {url: u1, name: Sam Doe, divisions: [Lightweight], nickname: x}\n  - {url: u2, name: Sam Doe (Tall), divisions: []}\n")
    cfg = ingest.load_disambiguation(p)
    assert cfg["Sam Doe"][1] == {"url": "u2", "name": "Sam Doe (Tall)", "divisions": [], "bout_urls": []}
    assert ingest.load_disambiguation(tmp_path / "absent.yaml") == {}


# ---------- the repository file against the repository data ----------

def test_repository_config_settles_the_repository_fighter_files():
    """Every shared name in data/raw has entries for exactly its fighter pages, and every bout of a shared
    name is claimed (the same checks ingest.main runs before writing anything)."""
    cfg = ingest.load_disambiguation()
    assert "Bruno Silva" in cfg
    tott, details = ingest.read_fighter_files()
    shared = ingest.shared_display_names(tott, details)
    assert set(shared) == set(cfg)
    bouts = pd.read_csv(ingest.PROC / "bouts.csv", parse_dates=["date"])
    # the processed file already carries the suffixed names; the assignment runs on the raw spelling
    plain = bouts.copy()
    for name, entries in cfg.items():
        for e in entries:
            plain["fighter_a"] = plain["fighter_a"].replace(e["name"], name)
            plain["fighter_b"] = plain["fighter_b"].replace(e["name"], name)
    assigned = ingest.assign_shared_bouts(plain, cfg)
    assert len(assigned) == int((plain["fighter_a"].isin(cfg) | plain["fighter_b"].isin(cfg)).sum())


def test_processed_bouts_carry_the_configured_names_in_the_configured_divisions(bouts: pd.DataFrame):
    """In data/processed/bouts.csv each configured display name appears only in its own divisions (or
    its explicit bouts), and the suffixed Bruno Silva is the middleweight."""
    cfg = ingest.load_disambiguation()
    for name, entries in cfg.items():
        for e in entries:
            mine = bouts[(bouts["fighter_a"] == e["name"]) | (bouts["fighter_b"] == e["name"])]
            allowed = mine["division"].isin(e["divisions"]) | mine["bout_url"].isin(e["bout_urls"])
            assert allowed.all(), f"{e['name']} has bouts outside its configured divisions"
            if not e["divisions"] and not e["bout_urls"]:
                assert mine.empty, f"{e['name']} is configured with no bouts but has {len(mine)}"
    mw = bouts[(bouts["fighter_a"] == "Bruno Silva (Blindado)") | (bouts["fighter_b"] == "Bruno Silva (Blindado)")]
    assert len(mw) == 11 and set(mw["division"]) == {"Middleweight"}
    fly = bouts[(bouts["fighter_a"] == "Bruno Silva") | (bouts["fighter_b"] == "Bruno Silva")]
    assert len(fly) == 12 and set(fly["division"]) == {"Flyweight", "Bantamweight"}


def test_processed_fighters_have_one_row_per_fighter_page():
    f = pd.read_csv(ingest.PROC / "fighters.csv")
    assert f["fighter"].is_unique and f["fighter_url"].is_unique
    by_url = f.set_index("fighter_url")
    for name, entries in ingest.load_disambiguation().items():
        for e in entries:
            assert by_url.loc[e["url"], "fighter"] == e["name"]
