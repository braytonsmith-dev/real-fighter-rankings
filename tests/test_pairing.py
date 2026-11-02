"""Scoring and conditional-logit checks for the next-opponent lists (src/mmalab/pairing.py)."""
import numpy as np
import pandas as pd

from mmalab.pairing import _metrics, _positions, fit_clogit


def test_positions_and_metrics():
    df = pd.DataFrame({"qid": [0, 0, 0, 1, 1, 2, 2],
                       "s": [0.1, 0.9, 0.5, 0.2, 0.8, 0.3, 0.4],
                       "target": [0, 0, 1, 1, 0, 0, 0]})        # query 2: real opponent not in the pool
    pos = _positions(df, "s")
    assert pos.loc[0] == 2 and pos.loc[1] == 2 and 2 not in pos.index
    m = _metrics(pos, pd.Index([0, 1, 2]))
    assert m["top1"] == 0.0 and m["top3"] == round(2 / 3, 4)
    assert m["mrr"] == round((0.5 + 0.5 + 0) / 3, 4)            # absent opponent scores 0, not dropped


def test_clogit_recovers_preference_for_close_rank():
    rng = np.random.default_rng(1)
    rows = []
    for q in range(400):
        gap = rng.integers(0, 30, 20).astype(float)
        p = np.exp(-0.3 * gap)
        t = rng.choice(20, p=p / p.sum())
        rows += [(q, g, float(i == t)) for i, g in enumerate(gap)]
    d = pd.DataFrame(rows, columns=["qid", "gap", "target"])
    w = fit_clogit(d[["gap"]].to_numpy(), d["target"].to_numpy(), d["qid"].to_numpy(), l2=0.01)
    assert -0.4 < w[0] < -0.2
