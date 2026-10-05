"""
elo.py - Chronological Elo rating engine for UFC bouts.

Design choices (all tunable through EloParams):
  * K-factor is larger for a fighter's first `n_new` UFC bouts so debutants
    converge quickly (same idea FIDE uses for new players).
  * Finishes (KO/TKO, SUB) move ratings more than decisions; split decisions
    move them less. This is the "dominant finishes" idea in the Meta rankings,
    expressed as a multiplier so the backtest can decide whether it helps.
  * Long layoffs regress a rating toward the mean before the next bout
    (`layoff_days`, `layoff_regress_per_year`). Set regress to 0 to disable.
  * Draws are scored 0.5. No-contests are skipped entirely.

Outputs:
  * bouts with pre-fight ratings for both fighters and the model win
    probability for fighter_a (this is what the backtest scores).
  * a rating history table (fighter, date, rating_after) so any module can
    ask "what was this fighter's rating on date X".
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


@dataclass
class EloParams:
    k: float = 40.0
    k_new_mult: float = 1.5      # multiplier on K for first n_new bouts
    n_new: int = 5
    finish_mult: float = 1.25    # KO/TKO or SUB
    split_mult: float = 0.80     # split or majority decision
    layoff_days: int = 365       # layoff longer than this triggers regression
    layoff_regress_per_year: float = 0.0   # fraction of (rating - mean) removed per excess year
    mov_weight: float = 0.0      # weight on in-fight dominance vs binary result (0 = classic Elo)
    mov_scale: float = 3.0       # dominance per minute that maps to ~73% "performance win"
    win_floor: float = 0.0       # winner's effective score is at least this (0 = off)
    finish_floor: float = 0.0    # winner by KO/TKO or SUB scores at least this (0 = off)
    start: float = 1500.0
    # v1.1 shadow additions; the defaults reproduce v1.0 exactly
    corner_adv: float = 0.0      # rating points credited to the first-listed (red corner) fighter in the expected score
    mov_damp: float = 0.0        # FiveThirtyEight-style damping of the dominance weight for favorites: w * 2.2 / (mov_damp * edge + 2.2)

    def to_dict(self) -> dict:
        return asdict(self)


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def run_elo(bouts: pd.DataFrame, p: EloParams | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = p or EloParams()
    df = bouts.sort_values(["date", "bout_id"]).reset_index(drop=True)
    has_dom = "dominance_a" in df.columns

    rating: dict[str, float] = {}
    n_fights: dict[str, int] = {}
    last_date: dict[str, pd.Timestamp] = {}

    pre_a, pre_b, prob_a, post_a, post_b = [], [], [], [], []
    hist_rows = []

    for row in df.itertuples(index=False):
        a, b, d = row.fighter_a, row.fighter_b, row.date
        ra = rating.get(a, p.start)
        rb = rating.get(b, p.start)

        # layoff regression toward the mean, applied before the bout
        if p.layoff_regress_per_year > 0:
            for name, r in ((a, ra), (b, rb)):
                ld = last_date.get(name)
                if ld is not None:
                    gap = (d - ld).days
                    if gap > p.layoff_days:
                        excess_years = (gap - p.layoff_days) / 365.25
                        shrink = min(1.0, p.layoff_regress_per_year * excess_years)
                        r = p.start + (r - p.start) * (1 - shrink)
                        if name == a:
                            ra = r
                        else:
                            rb = r

        ea = expected(ra + p.corner_adv, rb)
        pre_a.append(ra); pre_b.append(rb); prob_a.append(ea)

        if pd.isna(row.result_a):          # no contest: no rating change
            post_a.append(ra); post_b.append(rb)
            rating[a], rating[b] = ra, rb
            continue

        sa = float(row.result_a)
        # margin-of-victory blend: listen partly to how dominant the fight was
        if p.mov_weight > 0 and has_dom:
            dom = getattr(row, "dominance_a")
            if dom is not None and not pd.isna(dom):
                perf = 1.0 / (1.0 + np.exp(-dom / p.mov_scale))
                w = p.mov_weight
                if p.mov_damp > 0:
                    # a favorite is expected to dominate: shrink the dominance credit by its pre-fight edge
                    edge = (ra - rb) if dom > 0 else (rb - ra)
                    w = w * 2.2 / (p.mov_damp * max(0.0, edge) + 2.2)
                sa = (1 - w) * sa + w * perf
                # floors: a win, and especially a finish, is never scored as a loss
                res = float(row.result_a)
                is_finish = row.method in ("KO/TKO", "SUB")
                if res == 1.0:
                    sa = max(sa, p.win_floor, p.finish_floor if is_finish else 0.0)
                elif res == 0.0:
                    sa = min(sa, 1 - p.win_floor, 1 - (p.finish_floor if is_finish else 0.0))
        mult = 1.0
        if row.method in ("KO/TKO", "SUB"):
            mult = p.finish_mult
        elif row.method in ("S-DEC", "M-DEC"):
            mult = p.split_mult

        ka = p.k * (p.k_new_mult if n_fights.get(a, 0) < p.n_new else 1.0) * mult
        kb = p.k * (p.k_new_mult if n_fights.get(b, 0) < p.n_new else 1.0) * mult

        na = ra + ka * (sa - ea)
        nb = rb + kb * ((1 - sa) - (1 - ea))
        rating[a], rating[b] = na, nb
        n_fights[a] = n_fights.get(a, 0) + 1
        n_fights[b] = n_fights.get(b, 0) + 1
        last_date[a] = d; last_date[b] = d
        post_a.append(na); post_b.append(nb)
        hist_rows.append((a, d, row.bout_id, row.division, na, n_fights[a]))
        hist_rows.append((b, d, row.bout_id, row.division, nb, n_fights[b]))

    df["elo_pre_a"] = pre_a
    df["elo_pre_b"] = pre_b
    df["p_a"] = prob_a
    df["elo_post_a"] = post_a
    df["elo_post_b"] = post_b
    hist = pd.DataFrame(hist_rows, columns=["fighter", "date", "bout_id", "division", "rating", "ufc_fights"])
    return df, hist


def current_ratings(hist: pd.DataFrame) -> pd.DataFrame:
    """Latest rating per fighter, plus last bout date and last division."""
    last = hist.sort_values(["date", "bout_id"]).groupby("fighter").tail(1)
    return last.rename(columns={"date": "last_fight", "division": "last_division"}).reset_index(drop=True)


def rating_on_date(hist: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Rating each fighter carried into `as_of` (uses bouts strictly before that date)."""
    h = hist[hist["date"] < as_of]
    return current_ratings(h)
