"""
board_tune.py - Walk-forward tuning harness for the REAL resume board (v1.1 development).

Why this exists. resume_board.build() rebuilds the whole board for one date in about a minute, which
is fine for publishing and far too slow for choosing between hundreds of candidate rule sets. This
module runs the rating engine once over the full history (the engine is sequential, so a bout's
record is the same whichever later date we evaluate from), then precomputes a panel:

  dates   board dates every `step_days` from `start` to the last bout
  F       one row per (date, eligible fighter): division, rating after inactivity, title flags
  I       one row per (date, ledger item): every decided bout of a fighter on that board, with
          the item's age, the opponent's rank going in, and the opponent's standing afterwards
          (official rank now, rating position now, rating position two years on)
  L5      one row per (date, fighter, one of the last five decided bouts)
  E       evaluation bouts: every decided bout between two fighters on the same divisional board
          at the preceding panel date

score_panel(panel, params) turns a parameter dict into a score for every (date, fighter) in a few
seconds, evaluate() scores those against E (pairwise concordance; log loss through a one-parameter
logistic map), and walk_forward() tunes by coordinate descent on every panel date before a test
year and reports held-out results for that year, 2017 through the last full year.

The placement rules (head-to-head, title cycle) are not part of the harness; the selected rule set is
verified afterwards with full builds. Nothing here touches config/weights.yaml or the v1.0 outputs.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.official_ranks import OfficialRanks
from mmalab.rankings import RANKED_DIVISIONS, champions
from mmalab.resume import ResumeParams, run_resume
from mmalab.resume_board import (assign_divisions, division_overrides_as_of, exclusions_as_of, interim_as_of,
                                 layoffs_as_of, reserved_as_of)

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"
CFG = ROOT / "config"

TIER_LIMITS = (0, 5, 10, 15)          # champion, top 5, top 10, top 15 (rank limits, inclusive)
WIN_TIERS = (2.0, 1.5, 1.0, 0.5)      # v1.0 quality-win values by tier (then 0.25 for a proven veteran)
UNRANKED = 99.0


# --------------------------------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------------------------------

def v10_params() -> dict:
    """The frozen v1.0 board rules, expressed in this module's parameter dictionary."""
    rc = yaml.safe_load((CFG / "weights.yaml").read_text())["resume"]
    return {
        "w_rating": float(rc["weights"]["rating"]),
        "horizon": {"kind": "steps", "steps": {float(k): float(v) for k, v in rc["horizons"].items()}},
        "proof_value": float(rc["ledger"]["proof_of_concept"]),
        "loss": {"mode": "v10", "years": float(rc.get("decisive_loss_years", 3)), "tiers": [0.0, 1.0, 1.0, 1.0],
                 "dominant_extra": 0.0, "decay": "flat"},
        "hindsight": {"mode": "none", "alpha_win": 1.0, "alpha_loss": 1.0},
        "form": {"mode": "buckets", "buckets": {str(k): float(v) for k, v in rc["form_penalty"].items()},
                 "tiers": [0.05, 0.1, 0.15, 0.2], "cap": 0.45,          # used only when mode is "tiered"
                 "bad_loss": {"rank_above": 10, "per_loss": 0.0, "cap": 0.3}},
    }


def bplus0_params() -> dict:
    """The B+0 candidate evaluated on Oct 20, 2026 with full builds (43 boards)."""
    p = v10_params()
    p["loss"] = {"mode": "tiers", "years": 3.0, "tiers": [0.25, 0.5, 0.75, 1.0], "dominant_extra": 0.0, "decay": "flat"}
    p["form"] = {"mode": "buckets", "buckets": {"2-3": 0.10, "1-4": 0.30, "0-5": 0.40}, "tiers": [0.05, 0.1, 0.15, 0.2], "cap": 0.45,
                 "bad_loss": {"rank_above": 10, "per_loss": 0.10, "cap": 0.30}}
    return p


def params_to_overrides(p: dict) -> dict:
    """Translate a parameter dict into the `overrides` mapping resume_board.build() accepts."""
    over: dict = {"weights": {"rating": p["w_rating"], "quality_wins": round(1.0 - p["w_rating"], 6)},
                  "ledger": {"proof_of_concept": p["proof_value"]},
                  "form_penalty": dict(p["form"]["buckets"]) if p["form"]["mode"] == "buckets" else {},
                  "decisive_loss_years": p["loss"]["years"]}
    h = p["horizon"]
    if h["kind"] == "steps":
        over["horizons"] = {int(k) if float(k).is_integer() else k: v for k, v in h["steps"].items()}
    else:
        over["horizon_decay"] = {"full_years": h["full_years"], "tau": h["tau"], "max_years": h.get("max_years", 15)}
    if p["loss"]["mode"] == "tiers":
        c = p["loss"]["tiers"]
        over["ledger"]["loss_tiers"] = [[0, c[0]], [5, c[0]], [10, c[1]], [15, c[2]], [999, c[3]]]
        over["ledger"]["dominant_extra"] = p["loss"]["dominant_extra"]
        over["ledger"]["loss_decay"] = p["loss"]["decay"]
    if p["hindsight"]["mode"] != "none":
        over["hindsight"] = dict(p["hindsight"])
    if p["form"]["mode"] == "tiered":
        over["form_loss_tiers"] = {"tiers": [[0, p["form"]["tiers"][0]], [5, p["form"]["tiers"][0]], [10, p["form"]["tiers"][1]],
                                             [15, p["form"]["tiers"][2]], [999, p["form"]["tiers"][3]]], "cap": p["form"]["cap"]}
    bl = p["form"]["bad_loss"]
    if bl["per_loss"] > 0:
        over["form_bad_loss"] = {"rank_above": bl["rank_above"], "per_loss": bl["per_loss"], "cap": bl["cap"]}
    return over


# --------------------------------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------------------------------

def _tier_index(pos: np.ndarray) -> np.ndarray:
    """0 champion, 1 top 5, 2 top 10, 3 top 15, 4 unranked. pos is an official or model position (0 = champion)."""
    pos = np.asarray(pos, dtype=float)
    idx = np.full(pos.shape, 4, dtype=int)
    for i, lim in reversed(list(enumerate(TIER_LIMITS))):
        idx = np.where(pos <= lim, i, idx)
    return idx


@dataclass
class Panel:
    engine: dict
    step_days: int = 14
    start: str = "2014-01-05"
    max_item_years: float = 15.5
    post_years: float = 2.0
    dates: list = field(default_factory=list)
    F: pd.DataFrame | None = None
    I: pd.DataFrame | None = None
    L5: pd.DataFrame | None = None
    E: pd.DataFrame | None = None
    build_seconds: float = 0.0

    def build(self) -> "Panel":
        t0 = time.time()
        rc = yaml.safe_load((CFG / "weights.yaml").read_text())["resume"]
        inact = rc["inactivity"]
        bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
        out, hist = run_resume(bouts, ResumeParams(**{**rc["engine"], **self.engine}))
        last_bout = bouts["date"].max()
        dates = pd.date_range(self.start, last_bout + pd.Timedelta(days=1), freq=f"{self.step_days}D")
        if dates[-1] <= last_bout:
            dates = dates.append(pd.DatetimeIndex([last_bout + pd.Timedelta(days=1)]))
        self.dates = list(dates)

        names = pd.concat([out["fighter_a"], out["fighter_b"]]).dropna().unique().tolist()
        official = OfficialRanks(names)

        hist = hist.sort_values(["date", "bout_id"]).reset_index(drop=True)
        appear = pd.concat([out[["date", "fighter_a"]].rename(columns={"fighter_a": "fighter"}),
                            out[["date", "fighter_b"]].rename(columns={"fighter_b": "fighter"})]).sort_values("date")
        dec = out[out["result_a"].isin([0.0, 1.0])].copy()
        dec["winner"] = np.where(dec["result_a"] == 1.0, dec["fighter_a"], dec["fighter_b"])
        dec["loser"] = np.where(dec["result_a"] == 1.0, dec["fighter_b"], dec["fighter_a"])
        # veteran flag at fight time: the engine gave an unranked opponent 0.25 only when he was a proven winner
        dec["vet_win"] = dec["quality_win"] & (dec["qw_value"] == 0.25)
        # long form of every decided bout, one row per participant
        long = pd.concat([
            pd.DataFrame({"fighter": dec["winner"], "opp": dec["loser"], "date": dec["date"], "bout_id": dec["bout_id"],
                          "division": dec["division"], "won": True, "opp_pos_then": dec["loser_pos"].astype(float),
                          "qw_value": dec["qw_value"].astype(float), "vet": dec["vet_win"], "decisive": False,
                          "proof": False, "top10": dec["top10_win"], "top15": dec["top15_win"]}),
            pd.DataFrame({"fighter": dec["loser"], "opp": dec["winner"], "date": dec["date"], "bout_id": dec["bout_id"],
                          "division": dec["division"], "won": False, "opp_pos_then": dec["winner_pos"].astype(float),
                          "qw_value": 0.0, "vet": False, "decisive": dec["decisive_loss"].astype(bool),
                          "proof": dec["proof"].astype(bool), "top10": False, "top15": False}),
        ]).sort_values(["date", "bout_id"]).reset_index(drop=True)
        long["opp_pos_then"] = long["opp_pos_then"].fillna(UNRANKED)

        F_parts, I_parts, L_parts, E_parts = [], [], [], []
        rating_now_cache: dict[int, pd.Series] = {}

        def rating_before(d: pd.Timestamp) -> pd.Series:
            h = hist[hist["date"] < d]
            return h.groupby("fighter")["rating"].last()

        for di, d in enumerate(self.dates):
            # roster facts as they stood on the board date (dated override files), never today's state
            injured, gone = set(layoffs_as_of(d)), set(exclusions_as_of(d))
            div_over, interim, reserved = division_overrides_as_of(d), interim_as_of(d), reserved_as_of(d)
            r = rating_before(d)
            rating_now_cache[di] = r
            o = out[out["date"] < d]
            last_app = appear[appear["date"] < d].groupby("fighter")["date"].max()
            f = pd.DataFrame({"rating_raw": r, "last_fight": last_app.reindex(r.index)})
            f["division"] = assign_divisions(o, d).reindex(f.index)
            for name, dv in div_over.items():
                if name in f.index:
                    f.loc[name, "division"] = dv
            f["days_since"] = (d - f["last_fight"]).dt.days
            f["injury"] = f.index.isin(injured)
            max_days = np.where(f["injury"], inact["injury_max_days"], inact["max_days"])
            f = f[(f["days_since"] <= max_days) & f["division"].isin(RANKED_DIVISIONS) & ~f.index.isin(gone)].copy()
            over = ((f["days_since"] - inact["grace_days"]) / (inact["max_days"] - inact["grace_days"])).clip(0, 1)
            f["rating"] = f["rating_raw"] - np.where(f["injury"], 0.0, over * inact["max_penalty_points"])
            ch = champions(o, d)
            for dv, name in list(ch.items()) + list(interim.items()) + list(reserved.items()):
                if name in f.index:
                    f.loc[name, "division"] = dv
            f["champion"] = np.array([ch.get(dv) == n for n, dv in zip(f.index, f["division"])], dtype=bool)
            other_title = np.array([interim.get(dv) == n or reserved.get(dv) == n for n, dv in zip(f.index, f["division"])], dtype=bool)
            f["titled"] = f["champion"].to_numpy() | other_title
            f["di"] = di
            f = f.reset_index().rename(columns={"index": "fighter"})
            F_parts.append(f[["di", "fighter", "division", "rating", "rating_raw", "champion", "titled", "days_since"]])

            on_board = set(f["fighter"])
            # ledger items for fighters on this board
            items = long[(long["date"] < d) & long["fighter"].isin(on_board)].copy()
            items["age"] = (d - items["date"]).dt.days / 365.25
            items = items[items["age"] <= self.max_item_years]
            items["di"] = di
            # the opponent's standing afterwards: official rank as of d; rating position as of d
            items["opp_pos_now_off"] = [official.rank(n, dv, d) for n, dv in zip(items["opp"], items["division"])]
            items["opp_pos_now_off"] = items["opp_pos_now_off"].astype(float).fillna(UNRANKED)
            opp_rating_now = r.reindex(items["opp"]).to_numpy()
            items["opp_rpos_now"] = _rating_positions(f, items["division"].to_numpy(), opp_rating_now)
            I_parts.append(items)

            # last five decided bouts before d, for fighters on the board
            l5 = long[(long["date"] < d) & long["fighter"].isin(on_board)].groupby("fighter").tail(5).copy()
            l5["di"] = di
            L_parts.append(l5[["di", "fighter", "won", "opp_pos_then", "opp", "division", "date"]])

            # evaluation bouts until the next panel date
            d_next = self.dates[di + 1] if di + 1 < len(self.dates) else last_bout + pd.Timedelta(days=1)
            e = dec[(dec["date"] >= d) & (dec["date"] < d_next)].copy()
            fd = dict(zip(f["fighter"], f["division"]))
            keep = np.array([fd.get(a) == dv and fd.get(b) == dv for a, b, dv in zip(e["fighter_a"], e["fighter_b"], e["division"])], dtype=bool)
            e = e.loc[keep].copy()
            e["di"] = di
            E_parts.append(e[["di", "date", "event", "division", "title_fight", "fighter_a", "fighter_b", "result_a", "bout_url"]])

        self.F = pd.concat(F_parts, ignore_index=True)
        self.I = pd.concat(I_parts, ignore_index=True)
        self.L5 = pd.concat(L_parts, ignore_index=True)
        self.E = pd.concat(E_parts, ignore_index=True)

        # opponent's rating position `post_years` after the bout (or now, if sooner): the hindsight measure that
        # judges a result by how the opponent's career went next, without charging for decline years later
        self._add_post_positions(hist)
        self.build_seconds = time.time() - t0
        return self

    def _add_post_positions(self, hist: pd.DataFrame) -> None:
        I = self.I
        date_arr = np.array([np.datetime64(d) for d in self.dates])
        t_post = np.minimum((I["date"] + pd.to_timedelta(self.post_years * 365.25, unit="D")).to_numpy(),
                            date_arr[I["di"].to_numpy()])
        # panel date at or before t_post
        pdi = np.searchsorted(date_arr, t_post, side="right") - 1
        pdi = np.clip(pdi, 0, len(self.dates) - 1)
        # opponent rating as of that panel date: last hist rating before it
        h = hist.sort_values("date")
        h_dates = h["date"].to_numpy()
        h_f = h["fighter"].to_numpy()
        h_r = h["rating"].to_numpy()
        # build per-fighter arrays
        by_f: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for name, g in h.groupby("fighter"):
            by_f[name] = (g["date"].to_numpy(), g["rating"].to_numpy())
        opp_r_post = np.full(len(I), np.nan)
        opps = I["opp"].to_numpy()
        tp_dates = date_arr[pdi]
        for i in range(len(I)):
            arr = by_f.get(opps[i])
            if arr is None:
                continue
            j = np.searchsorted(arr[0], tp_dates[i], side="left") - 1
            if j >= 0:
                opp_r_post[i] = arr[1][j]
        # position among the fighters on the board at that panel date, same division
        F = self.F
        pos = np.full(len(I), UNRANKED)
        key = pd.DataFrame({"pdi": pdi, "division": I["division"].to_numpy(), "r": opp_r_post})
        for (pd_i, dv), idx in key.groupby(["pdi", "division"]).indices.items():
            fb = F[(F["di"] == pd_i) & (F["division"] == dv)]
            if fb.empty:
                continue
            sorted_r = np.sort(fb["rating_raw"].to_numpy())
            rr = key["r"].to_numpy()[idx]
            better = len(sorted_r) - np.searchsorted(sorted_r, rr, side="right")
            p = better + 1.0
            p[np.isnan(rr)] = UNRANKED
            pos[idx] = p
        I["opp_rpos_post"] = pos


def _rating_positions(f: pd.DataFrame, divisions: np.ndarray, ratings: np.ndarray) -> np.ndarray:
    """1 + number of fighters on this board in `division` whose raw rating exceeds `rating`; 99 when unknown."""
    pos = np.full(len(divisions), UNRANKED)
    for dv, g in f.groupby("division"):
        m = divisions == dv
        if not m.any():
            continue
        sorted_r = np.sort(g["rating_raw"].to_numpy())
        rr = ratings[m]
        better = len(sorted_r) - np.searchsorted(sorted_r, rr, side="right")
        p = better + 1.0
        p[np.isnan(rr)] = UNRANKED
        pos[m] = p
    return pos


# --------------------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------------------

def horizon_weights(age: np.ndarray, h: dict) -> np.ndarray:
    if h["kind"] == "steps":
        w = np.zeros_like(age, dtype=float)
        remaining = np.ones_like(age, dtype=bool)
        for lim in sorted(h["steps"]):
            m = remaining & (age <= float(lim))
            w[m] = float(h["steps"][lim])
            remaining &= ~m
        return w
    # continuous: full credit for `full_years`, then exponential with time constant tau, zero after max_years
    full, tau, mx = float(h["full_years"]), float(h["tau"]), float(h.get("max_years", 15))
    w = np.where(age <= full, 1.0, np.exp(-(age - full) / tau))
    return np.where(age <= mx, w, 0.0)


def _tier_values(pos: np.ndarray, values: tuple | list, unranked_value: np.ndarray | float) -> np.ndarray:
    idx = _tier_index(pos)
    v = np.asarray(list(values) + [0.0], dtype=float)[idx]
    return np.where(idx == 4, unranked_value, v)


def ledger_values(I: pd.DataFrame, p: dict) -> np.ndarray:
    """Signed ledger contribution of every item row under params p (before per-fighter summation)."""
    age = I["age"].to_numpy()
    hw = horizon_weights(age, p["horizon"])
    won = I["won"].to_numpy()
    proof = I["proof"].to_numpy()
    decisive = I["decisive"].to_numpy()
    pos_then = I["opp_pos_then"].to_numpy()
    hs = p["hindsight"]
    if hs["mode"] == "none":
        pos_now = pos_then
    elif hs["mode"] == "now_official":
        pos_now = I["opp_pos_now_off"].to_numpy()
    elif hs["mode"] == "now_rating":
        pos_now = I["opp_rpos_now"].to_numpy()
    elif hs["mode"] == "post_rating":
        pos_now = I["opp_rpos_post"].to_numpy()
    else:
        raise ValueError(hs["mode"])

    # wins: v1.0 value then (tiers plus the proven-veteran 0.25), blended with the value by the opponent's later standing
    win_then = I["qw_value"].to_numpy()
    vet = I["vet"].to_numpy().astype(float) * 0.25
    win_now = _tier_values(pos_now, WIN_TIERS, vet)
    aw = float(hs["alpha_win"]) if hs["mode"] != "none" else 1.0
    win_val = np.where(won, hw * (aw * win_then + (1 - aw) * win_now), 0.0)

    # proof-of-concept losses earn credit; other losses cost
    proof_val = np.where(~won & proof, hw * float(p["proof_value"]), 0.0)
    L = p["loss"]
    within = age <= float(L["years"])
    # flat: every loss inside the window costs its full tier value; horizon: the loss fades on the same
    # schedule as a win of the same age (v1.0 is flat inside three years, where the horizon weight is 1 anyway)
    lw = np.where(within, hw if L.get("decay") == "horizon" else 1.0, 0.0)
    if L["mode"] == "v10":
        cost = np.where(decisive, 1.0, np.where(pos_then > 5, 1.0, 0.0))
    else:
        tiers = L["tiers"]
        c_then = _tier_values(pos_then, (tiers[0], tiers[0], tiers[1], tiers[2]), tiers[3])
        c_now = _tier_values(pos_now, (tiers[0], tiers[0], tiers[1], tiers[2]), tiers[3])
        al = float(hs["alpha_loss"]) if hs["mode"] != "none" else 1.0
        cost = al * c_then + (1 - al) * c_now + np.where(decisive, float(L["dominant_extra"]), 0.0)
    loss_val = np.where(~won & ~proof, -lw * cost, 0.0)
    return win_val + proof_val + loss_val


def form_penalties(L5: pd.DataFrame, keys: pd.Index, p: dict, panel: "Panel | None" = None) -> np.ndarray:
    """Form penalty per (di, fighter) key under params p."""
    fm = p["form"]
    lost = (~L5["won"].to_numpy()).astype(float)
    g = L5["_key"].to_numpy()
    n = len(keys)
    if fm["mode"] == "buckets":
        if panel is not None:
            wins, losses = panel._l5_wins, panel._l5_losses
        else:
            wins = np.bincount(g, weights=1 - lost, minlength=n).astype(int)
            losses = np.bincount(g, weights=lost, minlength=n).astype(int)
        table = np.zeros((6, 6))
        for rec, val in fm["buckets"].items():
            w, l = (int(x) for x in rec.split("-"))
            table[w, l] = float(val)
        pen = table[np.minimum(wins, 5), np.minimum(losses, 5)]
    else:
        tiers = fm["tiers"]
        cost = _tier_values(L5["opp_pos_then"].to_numpy(), (tiers[0], tiers[0], tiers[1], tiers[2]), tiers[3])
        pen = np.minimum(np.bincount(g, weights=lost * cost, minlength=n), float(fm["cap"]))
    bl = fm["bad_loss"]
    if bl["per_loss"] > 0:
        bad = lost * (L5["opp_pos_then"].to_numpy() > bl["rank_above"])
        pen = pen + np.minimum(np.bincount(g, weights=bad, minlength=n) * float(bl["per_loss"]), float(bl["cap"]))
    return pen


def prepare(panel: Panel) -> Panel:
    """Integer keys for fast aggregation. Call once after build()."""
    F = panel.F
    F["_key"] = np.arange(len(F))
    key_map = pd.Series(F["_key"].to_numpy(), index=pd.MultiIndex.from_arrays([F["di"], F["fighter"]]))
    panel.I["_key"] = key_map.reindex(pd.MultiIndex.from_arrays([panel.I["di"], panel.I["fighter"]])).to_numpy()
    panel.L5["_key"] = key_map.reindex(pd.MultiIndex.from_arrays([panel.L5["di"], panel.L5["fighter"]])).to_numpy()
    E = panel.E
    E["_ka"] = key_map.reindex(pd.MultiIndex.from_arrays([E["di"], E["fighter_a"]])).to_numpy()
    E["_kb"] = key_map.reindex(pd.MultiIndex.from_arrays([E["di"], E["fighter_b"]])).to_numpy()
    E["year"] = E["date"].dt.year
    # division groups for IDR scaling
    F["_grp"] = F.groupby(["di", "division"]).ngroup()
    panel._grp_index = F.groupby("_grp").indices
    panel._n_groups = int(F["_grp"].max()) + 1
    # last-five counts never change with the parameters, so compute them once
    lost = (~panel.L5["won"].to_numpy()).astype(float)
    g = panel.L5["_key"].to_numpy()
    panel._l5_wins = np.bincount(g, weights=1 - lost, minlength=len(F)).astype(int)
    panel._l5_losses = np.bincount(g, weights=lost, minlength=len(F)).astype(int)
    return panel


def idr_scale_groups(x: np.ndarray, grp: np.ndarray, n_groups: int) -> np.ndarray:
    """(x - median) / (q90 - q10) within each group, vectorised: one sort, then interpolated order statistics."""
    order = np.lexsort((x, grp))
    xs, gs = x[order], grp[order]
    counts = np.bincount(gs, minlength=n_groups)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])

    def q(frac: float) -> np.ndarray:
        pos = starts + frac * np.maximum(counts - 1, 0)
        lo = np.floor(pos).astype(int)
        hi = np.minimum(lo + 1, starts + np.maximum(counts - 1, 0))
        w = pos - lo
        return (1 - w) * xs[np.minimum(lo, len(xs) - 1)] + w * xs[np.minimum(hi, len(xs) - 1)]
    q10, q50, q90 = q(0.1), q(0.5), q(0.9)
    scale = np.maximum(q90 - q10, 1e-9)
    return (x - q50[grp]) / scale[grp]


def score_panel(panel: Panel, p: dict) -> np.ndarray:
    """Score for every row of panel.F under params p (same formula as resume_board.build)."""
    F = panel.F
    n = len(F)
    grp = F["_grp"].to_numpy()
    if not hasattr(panel, "_rating_scaled"):
        panel._rating_scaled = idr_scale_groups(F["rating"].to_numpy(dtype=float), grp, panel._n_groups)
    ledger = np.bincount(panel.I["_key"].to_numpy(), weights=ledger_values(panel.I, p), minlength=n)
    form = form_penalties(panel.L5, F.index, p, panel)
    rating_term = p["w_rating"] * panel._rating_scaled
    ledger_term = (1.0 - p["w_rating"]) * idr_scale_groups(ledger, grp, panel._n_groups)
    return rating_term + ledger_term - form


def positions_from_scores(panel: Panel, scores: np.ndarray) -> np.ndarray:
    """Published-style position: champion 0, other title holders 0, contenders by score order within division."""
    F = panel.F
    pos = np.zeros(len(F), dtype=int)
    titled = F["titled"].to_numpy()
    for _, idx in panel._grp_index.items():
        cont = idx[~titled[idx]]
        order = cont[np.argsort(-scores[cont], kind="stable")]
        pos[order] = np.arange(1, len(order) + 1)
    return pos


def fit_slope(diff: np.ndarray, y: np.ndarray, lo: float = 0.05, hi: float = 10.0) -> float:
    """One-parameter logistic map p = 1/(1+exp(-s*diff)) by golden-section search on log loss."""
    def ll(s):
        z = np.clip(s * diff, -30, 30)
        pr = 1 / (1 + np.exp(-z))
        pr = np.clip(pr, 1e-6, 1 - 1e-6)
        return -np.mean(y * np.log(pr) + (1 - y) * np.log(1 - pr))
    gr = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - gr * (b - a), a + gr * (b - a)
    for _ in range(60):
        if ll(c) < ll(d):
            b = d
        else:
            a = c
        c, d = b - gr * (b - a), a + gr * (b - a)
    return float((a + b) / 2)


def evaluate(panel: Panel, scores: np.ndarray, mask: np.ndarray | None = None, slope: float | None = None,
             fit_mask: np.ndarray | None = None) -> dict:
    """Concordance and log loss of `scores` on panel.E rows selected by mask. The slope is fitted on fit_mask rows
    (default: the same rows) unless given."""
    E = panel.E
    pos = positions_from_scores(panel, scores)
    ka, kb = E["_ka"].to_numpy(), E["_kb"].to_numpy()
    y = E["result_a"].to_numpy(dtype=float)
    pa, pb = pos[ka], pos[kb]
    conc = np.where(pa == pb, 0.5, ((pa < pb) == (y == 1.0)).astype(float))
    diff = scores[ka] - scores[kb]
    m = np.ones(len(E), dtype=bool) if mask is None else mask
    fm = m if fit_mask is None else fit_mask
    s = slope if slope is not None else fit_slope(diff[fm], y[fm])
    z = np.clip(s * diff, -30, 30)
    pr = np.clip(1 / (1 + np.exp(-z)), 1e-6, 1 - 1e-6)
    ll = -(y * np.log(pr) + (1 - y) * np.log(1 - pr))
    top = lambda n: ((pa <= n) & (pb <= n))
    res = {"bouts": int(m.sum()), "concordance": float(conc[m].mean()), "log_loss": float(ll[m].mean()),
           "brier": float(((pr - y) ** 2)[m].mean()), "slope": s,
           "top30": {"bouts": int((m & top(30)).sum()), "concordance": float(conc[m & top(30)].mean()) if (m & top(30)).any() else None,
                     "log_loss": float(ll[m & top(30)].mean()) if (m & top(30)).any() else None},
           "top15": {"bouts": int((m & top(15)).sum()), "concordance": float(conc[m & top(15)].mean()) if (m & top(15)).any() else None,
                     "log_loss": float(ll[m & top(15)].mean()) if (m & top(15)).any() else None}}
    return res, {"conc": conc, "ll": ll, "p": pr, "pa": pa, "pb": pb}


# --------------------------------------------------------------------------------------------------
# Search space and coordinate descent
# --------------------------------------------------------------------------------------------------

def default_space() -> dict:
    """Each entry: (getter path, list of candidate values). Paths are tuples into the params dict; a path ending in a
    callable sets several fields at once (used for the horizon and the loss tiers, which must stay monotone)."""
    horizons = [{"kind": "steps", "steps": {3.0: 1.0, 5.0: 0.6, 10.0: 0.3, 15.0: 0.1}}]
    for full in (1.0, 2.0, 3.0):
        for tau in (1.5, 2.5, 4.0, 6.0):
            horizons.append({"kind": "exp", "full_years": full, "tau": tau, "max_years": 15.0})
    loss_tiers = []
    for c in itertools.product((0.0, 0.25, 0.5), (0.25, 0.5, 0.75), (0.5, 0.75, 1.0), (0.75, 1.0, 1.25, 1.5)):
        if c[0] <= c[1] <= c[2] <= c[3]:
            loss_tiers.append(list(c))
    form_tiers = []
    for c in itertools.product((0.0, 0.05), (0.05, 0.1), (0.1, 0.15, 0.2), (0.15, 0.2, 0.3)):
        if c[0] <= c[1] <= c[2] <= c[3]:
            form_tiers.append(list(c))
    return {
        ("w_rating",): [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85],
        ("horizon",): horizons,
        ("proof_value",): [0.0, 0.25, 0.5, 0.75, 1.0],
        ("loss", "mode"): ["v10", "tiers"],
        ("loss", "tiers"): loss_tiers,
        ("loss", "dominant_extra"): [0.0, 0.25, 0.5],
        ("loss", "years"): [2.0, 3.0, 4.0, 6.0, 15.0],
        ("loss", "decay"): ["flat", "horizon"],
        ("hindsight", "mode"): ["none", "now_official", "now_rating", "post_rating"],
        ("hindsight", "alpha_win"): [0.0, 0.25, 0.5, 0.75, 1.0],
        ("hindsight", "alpha_loss"): [0.0, 0.25, 0.5, 0.75, 1.0],
        ("form", "mode"): ["buckets", "tiered"],
        ("form", "buckets"): [{"2-3": a, "1-4": b, "0-5": c} for a in (0.0, 0.05, 0.1, 0.15, 0.2)
                              for b in (0.1, 0.2, 0.3, 0.45, 0.6) for c in (0.2, 0.4, 0.6, 0.8) if a <= b <= c],
        ("form", "tiers"): form_tiers,
        ("form", "cap"): [0.3, 0.45, 0.6],
        ("form", "bad_loss", "per_loss"): [0.0, 0.05, 0.1, 0.15],
        ("form", "bad_loss", "rank_above"): [10, 15],
    }


def _get(p: dict, path: tuple):
    for k in path:
        p = p[k]
    return p


def _set(p: dict, path: tuple, v) -> dict:
    q = copy.deepcopy(p)
    r = q
    for k in path[:-1]:
        r = r[k]
    r[path[-1]] = copy.deepcopy(v)
    return q


def coordinate_descent(panel: Panel, train_mask: np.ndarray, start: dict, space: dict | None = None,
                       sweeps: int = 3, verbose: bool = False) -> tuple[dict, float, list]:
    """Minimise training log loss (slope refitted for every candidate) one parameter at a time."""
    space = space or default_space()
    best = copy.deepcopy(start)
    best_ll = evaluate(panel, score_panel(panel, best), train_mask)[0]["log_loss"]
    trail = [("start", best_ll)]
    for sweep in range(sweeps):
        improved = False
        for path, values in space.items():
            if path == ("form", "tiers") and best["form"]["mode"] != "tiered":
                continue
            if path == ("form", "cap") and best["form"]["mode"] != "tiered":
                continue
            if path == ("form", "buckets") and best["form"]["mode"] != "buckets":
                continue
            if path in (("loss", "tiers"), ("loss", "dominant_extra")) and best["loss"]["mode"] != "tiers":
                continue
            if path in (("hindsight", "alpha_win"), ("hindsight", "alpha_loss")) and best["hindsight"]["mode"] == "none":
                continue
            cur = _get(best, path)
            for v in values:
                if v == cur:
                    continue
                cand = _set(best, path, v)
                ll = evaluate(panel, score_panel(panel, cand), train_mask)[0]["log_loss"]
                if ll < best_ll - 1e-6:
                    best, best_ll, cur, improved = cand, ll, v, True
                    trail.append((f"sweep {sweep + 1} {'.'.join(map(str, path))} -> {v}", ll))
                    if verbose:
                        print(f"  {trail[-1][0]}: {ll:.5f}", flush=True)
        if not improved:
            break
    return best, best_ll, trail


# --------------------------------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------------------------------

def event_block_bootstrap(d1: np.ndarray, d2: np.ndarray, events: np.ndarray, n: int = 5000, seed: int = 11) -> dict:
    """Paired difference d1 - d2 (per bout) with a bootstrap over events resampled whole."""
    rng = np.random.default_rng(seed)
    ev_ids, inv = np.unique(events, return_inverse=True)
    sums = np.bincount(inv, weights=d1 - d2, minlength=len(ev_ids))
    counts = np.bincount(inv, minlength=len(ev_ids)).astype(float)
    draws = np.empty(n)
    for i in range(n):
        pick = rng.integers(0, len(ev_ids), len(ev_ids))
        draws[i] = sums[pick].sum() / counts[pick].sum()
    return {"mean": float((d1 - d2).mean()), "ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]}


def walk_forward(panel: Panel, first_test_year: int = 2017, last_test_year: int | None = None, sweeps: int = 3,
                 verbose: bool = True) -> dict:
    E = panel.E
    years = E["year"].to_numpy()
    last_test_year = last_test_year or int(years.max())
    base10, baseB = v10_params(), bplus0_params()
    s10, sB = score_panel(panel, base10), score_panel(panel, baseB)
    rows, per_year, tuned_by_year = [], [], {}
    held_scores = np.full(len(E), np.nan)
    start = copy.deepcopy(base10)
    for yr in range(first_test_year, last_test_year + 1):
        train = years < yr
        test = years == yr
        t0 = time.time()
        best, ll_train, trail = coordinate_descent(panel, train, start, sweeps=sweeps, verbose=False)
        s_best = score_panel(panel, best)
        # slope for the test year is fitted on the training years only
        r_best, d_best = evaluate(panel, s_best, test, fit_mask=train)
        r_10, d_10 = evaluate(panel, s10, test, fit_mask=train)
        r_B, d_B = evaluate(panel, sB, test, fit_mask=train)
        per_year.append({"year": yr, "train_bouts": int(train.sum()), "test_bouts": int(test.sum()),
                         "tuned": {"concordance": r_best["concordance"], "log_loss": r_best["log_loss"]},
                         "v10": {"concordance": r_10["concordance"], "log_loss": r_10["log_loss"]},
                         "bplus0": {"concordance": r_B["concordance"], "log_loss": r_B["log_loss"]},
                         "train_log_loss": ll_train, "seconds": round(time.time() - t0, 1)})
        tuned_by_year[yr] = best
        rows.append(pd.DataFrame({"year": yr, "ll_tuned": d_best["ll"][test], "ll_10": d_10["ll"][test], "ll_B": d_B["ll"][test],
                                  "c_tuned": d_best["conc"][test], "c_10": d_10["conc"][test], "c_B": d_B["conc"][test],
                                  "event": E["event"].to_numpy()[test] + "|" + E["date"].dt.strftime("%Y-%m-%d").to_numpy()[test],
                                  "top15": ((d_10["pa"] <= 15) & (d_10["pb"] <= 15))[test]}))
        start = best       # warm start the next fold
        if verbose:
            print(f"{yr}: tuned {r_best['concordance']:.3f}/{r_best['log_loss']:.4f}  v1.0 {r_10['concordance']:.3f}/{r_10['log_loss']:.4f}"
                  f"  B+0 {r_B['concordance']:.3f}/{r_B['log_loss']:.4f}  ({time.time() - t0:.0f}s, {len(trail) - 1} moves)", flush=True)
    pooled = pd.concat(rows, ignore_index=True)
    ev = pooled["event"].to_numpy()
    summary = {
        "test_years": [first_test_year, last_test_year], "bouts": int(len(pooled)),
        "tuned": {"concordance": float(pooled["c_tuned"].mean()), "log_loss": float(pooled["ll_tuned"].mean())},
        "v10": {"concordance": float(pooled["c_10"].mean()), "log_loss": float(pooled["ll_10"].mean())},
        "bplus0": {"concordance": float(pooled["c_B"].mean()), "log_loss": float(pooled["ll_B"].mean())},
        "tuned_minus_v10": {"log_loss": event_block_bootstrap(pooled["ll_tuned"].to_numpy(), pooled["ll_10"].to_numpy(), ev),
                            "concordance": event_block_bootstrap(pooled["c_tuned"].to_numpy(), pooled["c_10"].to_numpy(), ev)},
        "tuned_minus_bplus0": {"log_loss": event_block_bootstrap(pooled["ll_tuned"].to_numpy(), pooled["ll_B"].to_numpy(), ev),
                               "concordance": event_block_bootstrap(pooled["c_tuned"].to_numpy(), pooled["c_B"].to_numpy(), ev)},
        "bplus0_minus_v10": {"log_loss": event_block_bootstrap(pooled["ll_B"].to_numpy(), pooled["ll_10"].to_numpy(), ev),
                             "concordance": event_block_bootstrap(pooled["c_B"].to_numpy(), pooled["c_10"].to_numpy(), ev)},
    }
    t15 = pooled[pooled["top15"]]
    summary["top15"] = {"bouts": int(len(t15)),
                        "tuned": {"concordance": float(t15["c_tuned"].mean()), "log_loss": float(t15["ll_tuned"].mean())},
                        "v10": {"concordance": float(t15["c_10"].mean()), "log_loss": float(t15["ll_10"].mean())}}
    return {"summary": summary, "per_year": per_year, "tuned_by_year": {str(k): v for k, v in tuned_by_year.items()},
            "pooled": pooled}


def stability_of_choices(tuned_by_year: dict) -> dict:
    """How often each parameter value was chosen across folds (a rough check on overfitting)."""
    out: dict = {}
    for yr, p in tuned_by_year.items():
        flat = {"w_rating": p["w_rating"], "horizon": json.dumps(p["horizon"], sort_keys=True), "proof_value": p["proof_value"],
                "loss.mode": p["loss"]["mode"], "loss.tiers": json.dumps(p["loss"]["tiers"]), "loss.dominant_extra": p["loss"]["dominant_extra"],
                "loss.years": p["loss"]["years"], "loss.decay": p["loss"]["decay"], "hindsight.mode": p["hindsight"]["mode"],
                "hindsight.alpha_win": p["hindsight"]["alpha_win"], "hindsight.alpha_loss": p["hindsight"]["alpha_loss"],
                "form.mode": p["form"]["mode"], "form.buckets": json.dumps(p["form"]["buckets"], sort_keys=True),
                "form.bad_loss": json.dumps(p["form"]["bad_loss"], sort_keys=True)}
        for k, v in flat.items():
            out.setdefault(k, {}).setdefault(str(v), []).append(yr)
    return out
