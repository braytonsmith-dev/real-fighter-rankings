"""Leakage and target checks for the matchmaking availability panel (src/mmalab/availability.py)."""
import numpy as np
import pandas as pd

from mmalab.availability import build_panel


def _bouts():
    rows = [  # date, a, b, result_a, method
        ("2019-01-10", "Ann", "Bea", 1.0, "KO/TKO"),
        ("2019-06-10", "Ann", "Cat", 0.0, "KO/TKO"),
        ("2020-01-01", "Ann", "Dee", 1.0, "U-DEC"),   # falls exactly on a snapshot date
        ("2020-03-15", "Bea", "Cat", 1.0, "SUB"),
        ("2020-07-01", "Cat", "Dee", 1.0, "U-DEC"),
    ]
    b = pd.DataFrame(rows, columns=["date", "fighter_a", "fighter_b", "result_a", "method"])
    b["division"] = "Lightweight"
    b["title_fight"] = False
    b["bout_id"] = range(len(b))
    return b


def _panel():
    b = _bouts()
    fighters = pd.DataFrame({"fighter": ["Ann", "Bea", "Cat", "Dee"],
                             "dob": ["1990-01-01", None, "1995-06-01", None]})
    elo = pd.DataFrame({"fighter": b["fighter_a"], "date": b["date"], "bout_id": b["bout_id"], "division": b["division"],
                        "rating": 1500.0, "ufc_fights": 1})
    return build_panel(b, fighters, elo, start="2019-12-01", end="2020-02-01")


def test_bout_on_snapshot_date_is_target_not_feature():
    P = _panel()
    ann = P[(P["fighter"] == "Ann") & (P["snapshot"] == "2020-01-01")].iloc[0]
    assert ann["n_bouts"] == 2                       # the Jan 1 bout is not in the features
    assert ann["days_since"] == (pd.Timestamp("2020-01-01") - pd.Timestamp("2019-06-10")).days
    assert ann["next_in_days"] == 0 and ann["y60"] == 1.0
    assert ann["last_ko_loss"] == 1.0                # last prior bout was the KO loss to Cat


def test_active_window_and_targets():
    P = _panel()
    dec = P[P["snapshot"] == "2019-12-01"].set_index("fighter")
    assert set(dec.index) == {"Ann", "Bea", "Cat"}   # Dee has not debuted yet
    assert dec.loc["Bea", "next_in_days"] == (pd.Timestamp("2020-03-15") - pd.Timestamp("2019-12-01")).days
    assert dec.loc["Bea", "y60"] == 0.0 and dec.loc["Bea", "y120"] == 1.0
    feb = P[P["snapshot"] == "2020-02-01"].set_index("fighter")
    assert np.isinf(feb.loc["Ann", "next_in_days"])
    assert feb.loc["Ann", "y120"] == 0.0              # left the data: a real "no", not censored
    # windows that close after the last bout in the data are left unscored
    assert np.isnan(feb.loc["Ann", "y180"])
