"""Unit tests for mmalab.decline: the vectorised prior-bout sums equal the plain loop, nothing from a later bout leaks
into an earlier row, a synthetic decliner gets a negative slope, the corner credit is recovered, and the as-of index
uses only bouts before its date."""
from __future__ import annotations

import numpy as np
import pandas as pd

from mmalab import decline as dc


def _table(rows: list[dict]) -> pd.DataFrame:
    """Rows carry fighter, date, age, r (residual) and optionally female; one synthetic row per fighter-bout."""
    t = pd.DataFrame(rows)
    t["date"] = pd.to_datetime(t["date"])
    t["bout_id"] = np.arange(len(t))
    t["side"] = "a"
    for c, v in (("event", "E"), ("opponent", "X"), ("division", "Lightweight"), ("won", np.nan), ("s", np.nan),
                 ("gap", 0.0), ("margin_raw", np.nan), ("e", 0.5)):
        if c not in t.columns:
            t[c] = v
    if "female" not in t.columns:
        t["female"] = 0
    t.attrs["outcome"] = "perf"
    return t


def _flat_coefs() -> dict[int, np.ndarray]:
    """A population curve that is identically zero, so adj equals r."""
    z = np.zeros(2 + len(dc.KNOTS))
    return {0: z, 1: z.copy()}


def _random_table(seed: int = 0, fighters: int = 40, max_bouts: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(fighters):
        n = rng.integers(1, max_bouts + 1)
        start = pd.Timestamp("2012-01-01") + pd.Timedelta(days=int(rng.integers(0, 2000)))
        dob_age = float(rng.uniform(20, 32))
        has_dob = rng.random() > 0.15
        for k in range(n):
            d = start + pd.Timedelta(days=int(k * rng.integers(90, 400)))
            rows.append({"fighter": f"F{i}", "date": d, "age": dob_age + (d - start).days / 365.25 if has_dob else np.nan,
                         "r": float(rng.normal(0, 0.35)), "female": int(i % 5 == 0)})
    return _table(rows)


def test_vectorised_terms_match_reference_loop():
    t = _random_table()
    coefs = dc.fit_population(t)
    for hp in (None, {"lambda_level": 2.0, "lambda_slope": 20.0, "half_life": 1.5}, {"lambda_slope": 1e9, "half_life": 1e6}):
        v = dc.individual_terms(t, coefs, hp).set_index("bout_id").sort_index()
        ref = dc.individual_terms_reference(t, coefs, hp).set_index("bout_id").sort_index()
        for c in ("n_prior", "ind_level", "ind_slope", "ind_pred", "pred"):
            assert np.allclose(v[c].to_numpy(dtype=float), ref[c].to_numpy(dtype=float), atol=1e-10), c


def test_no_look_ahead():
    t = _random_table(seed=3)
    coefs = _flat_coefs()
    base = dc.individual_terms(t, coefs).set_index("bout_id").sort_index()
    # perturb the LAST bout of every fighter: no earlier row may change
    t2 = t.copy()
    last_idx = t2.sort_values("date").groupby("fighter").tail(1).index
    t2.loc[last_idx, "r"] = 5.0
    after = dc.individual_terms(t2, coefs).set_index("bout_id").sort_index()
    earlier = ~t.set_index("bout_id").index.isin(t2.loc[last_idx, "bout_id"])
    for c in ("ind_level", "ind_slope", "ind_pred"):
        assert np.allclose(base.loc[earlier, c], after.loc[earlier, c]), c
    # and the perturbed rows themselves are unchanged too: a row's own residual is not in its prior sums
    assert np.allclose(base.loc[~earlier, "ind_pred"], after.loc[~earlier, "ind_pred"])


def test_first_rows_have_no_terms():
    t = _random_table(seed=5)
    v = dc.individual_terms(t, _flat_coefs())
    few = v["n_prior"] < dc.MIN_PRIOR
    assert (v.loc[few, "ind_pred"] == 0).all() and (v.loc[few, "ind_level"] == 0).all()


def test_synthetic_decliner_gets_negative_slope_and_prediction():
    # residuals fall 0.05 a year from age 30 to 38, on top of noise-free performance
    rows = [{"fighter": "Old", "date": pd.Timestamp("2015-01-01") + pd.DateOffset(months=8 * k), "age": 30 + k * 2 / 3,
             "r": 0.15 - 0.05 * (k * 2 / 3)} for k in range(13)]
    rows += [{"fighter": "Flat", "date": pd.Timestamp("2015-01-01") + pd.DateOffset(months=8 * k), "age": 30 + k * 2 / 3, "r": 0.0}
             for k in range(13)]
    t = _table(rows)
    v = dc.individual_terms(t, _flat_coefs(), {"lambda_level": 1.0, "lambda_slope": 1.0, "half_life": 1e6})
    old = v[v["fighter"] == "Old"].sort_values("date")
    assert old["ind_slope"].iloc[-1] < -0.02
    assert old["ind_pred"].iloc[-1] < old["ind_pred"].iloc[dc.MIN_PRIOR]
    flat = v[v["fighter"] == "Flat"]
    assert np.allclose(flat["ind_pred"], 0.0)


def test_slope_is_shrunk_off_at_huge_lambda():
    t = _random_table(seed=7)
    v = dc.individual_terms(t, _flat_coefs(), {"lambda_slope": 1e12})
    assert np.abs(v["ind_slope"]).max() < 1e-6
    assert np.allclose(v["ind_pred"], v["ind_level"])


def test_population_curve_recovers_a_linear_age_effect():
    rng = np.random.default_rng(1)
    age = rng.uniform(22, 40, 4000)
    t = _table([{"fighter": f"F{i}", "date": "2014-06-01", "age": a, "r": 0.1 - 0.01 * (a - 30) + rng.normal(0, 0.05)} for i, a in enumerate(age)])
    coefs = dc.fit_population(t)
    curve = dc.population_curve(np.array([25.0, 30.0, 35.0]), np.zeros(3, dtype=int), coefs)
    assert abs(curve[0] - 0.15) < 0.02 and abs(curve[1] - 0.10) < 0.02 and abs(curve[2] - 0.05) < 0.02
    # unknown age gets the neutral value 0
    assert dc.population_curve(np.array([np.nan]), np.zeros(1, dtype=int), coefs)[0] == 0.0


def test_corner_credit_is_recovered():
    rng = np.random.default_rng(2)
    n = 6000
    gap = rng.normal(0, 150, n)
    true_corner = 40.0
    e_true = 1.0 / (1.0 + 10 ** (-(gap + true_corner) / 400.0))
    t = pd.DataFrame({"side": "a", "gap": gap, "s": e_true + rng.normal(0, 0.1, n)})
    c = dc.fit_corner(t, np.ones(n, dtype=bool))
    assert abs(c - true_corner) < 8.0
    e = dc.expectation(t, c)
    assert abs(float((t["s"] - e).mean())) < 1e-3


def test_index_as_of_uses_only_earlier_bouts():
    rows = [{"fighter": "A", "date": f"20{15 + k // 2}-{1 + 6 * (k % 2):02d}-15", "age": 28 + k / 2, "r": 0.2} for k in range(8)]
    rows += [{"fighter": "B", "date": f"20{15 + k // 2}-{1 + 6 * (k % 2):02d}-15", "age": 28 + k / 2, "r": -0.2} for k in range(8)]
    rows += [{"fighter": "C", "date": "2018-03-01", "age": 25.0, "r": 0.3}]        # one bout: below MIN_PRIOR
    t = _table(rows)
    t["s"], t["e"] = 0.5 + t["r"], 0.5
    idx = dc.index_as_of(t, pd.Timestamp("2017-01-01"))
    assert set(idx["fighter"]) == {"A", "B"}
    # four bouts each before 2017 (2015-01, 2015-07, 2016-01, 2016-07)
    assert (idx["bouts_used"] == 4).all()
    assert idx.set_index("fighter").loc["A", "individual_level"] > 0 > idx.set_index("fighter").loc["B", "individual_level"]
    # as of a later date, more bouts are used and the age has moved on
    later = dc.index_as_of(t, pd.Timestamp("2019-01-01")).set_index("fighter")
    assert later.loc["A", "bouts_used"] == 8 and later.loc["A", "age"] > idx.set_index("fighter").loc["A", "age"]
