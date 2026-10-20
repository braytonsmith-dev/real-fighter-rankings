"""Invariants of data/processed/bouts.csv that every downstream module relies on.

ingest.build_bouts drops duplicate bout URLs, sorts by (date, event, bout_url) and numbers the rows
as bout_id. elo.py, resume.py and resume_board.py then order bouts by (date, bout_id), so bout_id
must be the chronological tie-breaker within a date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mmalab import ingest
from mmalab.rankings import RANKED_DIVISIONS

# Labels ingest.parse_division can emit for bouts that no board ranks.
NON_RANKED_LABELS = {"Women's Featherweight", "Catch Weight", "Open Weight", "Unknown"}

# UFC Ultimate Japan, 1997-12-21: the Sakuraba vs Silveira bout was ruled a no contest and fought
# again the same night. It is the only legitimate same-pair, same-date repeat in the data.
SAKURABA_SILVEIRA = ("Kazushi Sakuraba", "Marcus Silveira")
SAKURABA_SILVEIRA_DATE = pd.Timestamp("1997-12-21")


def _pair(df: pd.DataFrame) -> pd.Series:
    """Order-independent fighter pair, one tuple per row."""
    pairs = [tuple(sorted(p)) for p in zip(df["fighter_a"], df["fighter_b"])]
    return pd.Series(pairs, index=df.index)


def test_bout_url_is_present_and_unique(bouts: pd.DataFrame) -> None:
    assert bouts["bout_url"].notna().all()
    assert bouts["bout_url"].is_unique, "duplicate bout_url rows would be rated twice"


def test_fighter_names_are_present_and_distinct(bouts: pd.DataFrame) -> None:
    assert bouts["fighter_a"].notna().all() and bouts["fighter_b"].notna().all()
    assert (bouts["fighter_a"] != bouts["fighter_b"]).all()


def test_result_a_values(bouts: pd.DataFrame) -> None:
    decided = bouts["result_a"].dropna()
    assert set(decided.unique()) <= {0.0, 0.5, 1.0}
    # no-contests are NaN and exist, so the engines' NaN branch is exercised by real data
    assert bouts["result_a"].isna().any()


def test_dates_parse(bouts: pd.DataFrame) -> None:
    assert pd.api.types.is_datetime64_any_dtype(bouts["date"])
    assert bouts["date"].notna().all(), "an unmatched event date would silently sort to the end"
    assert bouts["date"].min() >= pd.Timestamp("1993-11-12")   # UFC 1
    assert bouts["date"].max() <= pd.Timestamp.today() + pd.Timedelta(days=1)


def test_bout_id_is_the_chronological_row_order(bouts: pd.DataFrame) -> None:
    assert (bouts["bout_id"].to_numpy() == np.arange(len(bouts))).all()
    by_id = bouts.sort_values("bout_id")
    assert by_id["date"].is_monotonic_increasing, "bout_id must never run backwards in time"
    # the exact ordering ingest.build_bouts produces, so (date, bout_id) sorts reproduce it
    expected = bouts.sort_values(["date", "event", "bout_url"])["bout_id"].to_numpy()
    assert (expected == np.arange(len(bouts))).all()


def test_same_pair_same_date_repeats_are_only_sakuraba_silveira(bouts: pd.DataFrame) -> None:
    keyed = bouts.assign(pair=_pair(bouts))
    dup = keyed[keyed.duplicated(subset=["pair", "date"], keep=False)]
    assert set(dup["pair"]) == {SAKURABA_SILVEIRA}
    assert set(dup["date"]) == {SAKURABA_SILVEIRA_DATE}
    assert len(dup) == 2
    # the no contest comes first, the re-fight second
    first, second = dup.sort_values("bout_id").itertuples()
    assert np.isnan(first.result_a) and second.result_a == 1.0


def test_division_labels_are_known(bouts: pd.DataFrame) -> None:
    labels = set(bouts["division"].unique())
    unknown = labels - set(RANKED_DIVISIONS) - NON_RANKED_LABELS
    assert not unknown, f"unexpected division labels: {sorted(unknown)}"
    assert set(RANKED_DIVISIONS) <= labels, "a ranked division with no bouts at all"


def test_ranked_divisions_are_a_subset_of_ingest_divisions() -> None:
    assert set(RANKED_DIVISIONS) <= set(ingest.DIVISIONS)
    assert NON_RANKED_LABELS - set(ingest.DIVISIONS) == {"Catch Weight", "Open Weight", "Unknown"}


def test_parse_division_prefers_womens_labels() -> None:
    assert ingest.parse_division("Women's Flyweight Bout") == "Women's Flyweight"
    assert ingest.parse_division("UFC Flyweight Title Bout") == "Flyweight"
    assert ingest.parse_division("Catch Weight Bout") == "Catch Weight"
    assert ingest.parse_division("Open Weight Bout") == "Open Weight"
    assert ingest.parse_division("") == "Unknown"
