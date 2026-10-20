"""
Tests for mmalab.official_ranks: every official ranking name resolves to a UFCStats name (or is an
allowlisted fighter with no UFCStats bouts), known lookups return the right rank, and the refresh
guard raises instead of silently treating a ranked fighter as unranked.

These run against the repository data (data/raw/ufc_rankings_history.csv, data/processed/bouts.csv),
because the deliverable under test is coverage of that data.
"""
from __future__ import annotations

import pandas as pd
import pytest

from mmalab import official_ranks
from mmalab.compare import norm
from mmalab.official_ranks import OfficialRanks, ROOT, RAW, load_aliases, load_unmatched_ok

BOUTS = ROOT / "data" / "processed" / "bouts.csv"


@pytest.fixture(scope="module")
def ufc_names() -> list[str]:
    b = pd.read_csv(BOUTS)
    return pd.concat([b["fighter_a"], b["fighter_b"]]).dropna().unique().tolist()


@pytest.fixture(scope="module")
def ranks(ufc_names) -> OfficialRanks:
    return OfficialRanks(ufc_names)


def test_every_ranking_name_resolves_or_is_allowlisted(ranks):
    """After the alias file, nothing is unmatched except fighters explicitly allowed to be."""
    assert ranks.unmatched - load_unmatched_ok() == set()
    assert not (set(load_aliases()) & ranks.unmatched), "an alias key is still unmatched"
    assert ranks.match_rate > 0.99


def test_alias_targets_exist_and_carry_ranking_rows(ranks, ufc_names):
    names = set(ufc_names)
    for key, target in load_aliases().items():
        assert target in names, f"alias target {target!r} (for {key!r}) is not a UFCStats name in bouts.csv"
        assert key != target, f"alias {key!r} maps to itself"
        assert any(target in rel["any"] for rel in ranks.by_date.values()), \
            f"alias {key!r} -> {target!r} attached no ranking rows"


def test_allowlisted_names_have_no_bouts(ufc_names):
    """A listed name that now has UFCStats bouts should match on its own: remove it from the allowlist."""
    normed = {norm(n) for n in ufc_names}
    for name in load_unmatched_ok():
        assert name not in set(ufc_names), f"{name!r} has bouts in bouts.csv; drop it from the allowlist"
        assert norm(name) not in normed, f"{name!r} matches a UFCStats name after normalisation"


def test_blank_fighter_rows_are_dropped(ranks):
    raw = pd.read_csv(RAW / "ufc_rankings_history.csv")
    assert raw["fighter"].isna().any(), "fixture assumption: the raw history has vacant-title rows"
    assert all(isinstance(n, str) and n for n in ranks.unmatched)
    assert all(isinstance(n, str) and n for rel in ranks.by_date.values() for _, n in rel["div"])


@pytest.mark.parametrize("name, division, date, expected", [
    ("Cristiane Justino", "Women's Featherweight", "2018-12-29", 0.0),   # Cris Cyborg, champion into the Nunes bout
    ("Cristiane Justino", "Women's Featherweight", "2017-12-30", 0.0),   # champion into the Holm bout
    ("Jacare Souza", "Middleweight", "2019-04-27", 4.0),                 # Ronaldo Souza into the Hermansson bout
    ("Bibulatov Magomed", "Flyweight", "2019-02-02", 11.0),              # Magomed Bibulatov into the Bontorin bout
    ("Timothy Johnson", "Heavyweight", "2017-03-18", 12.0),              # Tim Johnson into the Omielanczuk bout
    ("Yuta Sasaki", "Flyweight", "2018-11-17", 13.0),                    # Ulka Sasaki into the Pantoja bout
    ("Constantinos Philippou", "Middleweight", "2013-09-21", 7.0),       # Costas Philippou into the Carmont bout
    ("Rogerio Nogueira", "Light Heavyweight", "2016-05-14", 10.0),       # Antonio Rogerio Nogueira into the Cummins bout
    ("Francisco Rivera", "Bantamweight", "2015-06-06", 11.0),            # Francisco Rivera Jr. into the Caceres bout
    ("Mara Romero Borella", "Women's Flyweight", "2019-08-03", 10.0),    # Mara Borella into the Murphy bout
    ("Bruno Silva", "Flyweight", "2024-12-14", 12.0),                    # Bruno Gustavo da Silva into the Kape bout
    ("Luis Henrique", "Heavyweight", "2017-01-03", 15.0),                # Luis Henrique Barbosa, the one 2017-01-02 release
])
def test_aliased_fighters_are_ranked_at_fight_time(ranks, name, division, date, expected):
    got = ranks.rank(name, division, date)
    assert got is not None and got < 99
    assert got == expected


def test_unchanged_behaviour_for_direct_matches(ranks):
    assert ranks.rank("Jon Jones", "Light Heavyweight", "2013-04-27") == 0.0
    assert ranks.rank("Jon Jones", "Light Heavyweight", "2012-04-21") is None      # before the first release
    assert ranks.release_before("2013-01-01") is None
    assert ranks.rank("Cristiane Justino", "Women's Featherweight", "2019-07-27") == 99.0  # no longer on the board


def test_missing_alias_raises(monkeypatch, ufc_names):
    """Without the alias file the known spelling gaps must fail loudly, not degrade to unranked."""
    if not load_aliases():
        pytest.skip("no aliases configured")
    monkeypatch.setattr(official_ranks, "load_aliases", lambda *a, **k: {})
    with pytest.raises(ValueError, match="Cris Cyborg"):
        OfficialRanks(ufc_names)


def test_bad_alias_target_raises(monkeypatch, ufc_names):
    monkeypatch.setattr(official_ranks, "load_aliases", lambda *a, **k: {"Cris Cyborg": "Nobody Real"})
    with pytest.raises(ValueError, match="Nobody Real"):
        OfficialRanks(ufc_names)


def test_unmatched_outside_allowlist_raises(monkeypatch, ufc_names):
    allowed = load_unmatched_ok()
    if not allowed:
        pytest.skip("allowlist is empty")
    monkeypatch.setattr(official_ranks, "load_unmatched_ok", lambda *a, **k: set())
    with pytest.raises(ValueError, match=sorted(allowed)[0]):
        OfficialRanks(ufc_names)
