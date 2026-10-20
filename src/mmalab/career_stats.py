"""
career_stats.py - Per-fighter career statistics "as of" any date, computed only from bouts strictly
before that date, so nothing from the bout being predicted (or anything after it) can leak.

Two uses:
  * prediction features: `career_table` gives every (fighter, bout) row the fighter's cumulative
    record before that bout; `bout_features` lays both fighters' rows side by side per bout.
  * decline-risk analysis: `features_as_of` gives every fighter's record as of a board date, with
    layoff and age measured at that date.

Conventions:
  * Chronology is (date, bout_id), the same order elo.py uses. Same-night tournament bouts (all
    before 2000) are therefore ordered by bout_id, not by their real order on the card.
  * Cage time is fight_seconds / 60, unclipped (bout_stats.py clips at 30 s only for its per-minute
    dominance rate). Per-minute and per-15-minute rates divide by cage time in bouts that have round
    statistics (`stats_minutes`), so a bout without statistics adds no phantom minutes.
  * UFCStats recorded no control time before UFC 21 (July 1999). Control shares therefore divide by
    cage time at events where any control time was recorded (`ctrl_minutes`); an event-level flag
    keeps the few genuinely zero-control modern bouts in the denominator.
  * Missing statistics give NaN, never zero, except that a true debut (no prior bout at all) shows
    zero counts; `stats_bouts` tells the consumer how many prior bouts the statistics rest on.
  * A debut's layoff_days and win_rate_last5 are NaN. shadow.py fills layoff with 365 days and
    missing age differences with 0; this module leaves the filling to the model.

Column glossary. Unless marked bout_*, every column is cumulative over the fighter's prior UFC bouts
(before the bout, or before the as_of date). Counts are plain integers unless stated otherwise.
  fighter, opponent, bout_id, date, side   identity of the (fighter, bout) row; side is a or b
  n_bouts                 prior UFC bouts
  n_wins, n_losses, n_draws, n_nc   prior wins, losses, draws, no contests
  ko_wins, sub_wins       prior wins by KO/TKO and by submission
  ko_losses, sub_losses   prior losses by KO/TKO and by submission
  minutes                 prior cage time, all bouts (minutes)
  stats_bouts             prior bouts that have round statistics
  stats_minutes           cage time in those bouts (minutes); denominator of the per-minute rates
  ctrl_minutes            cage time in prior bouts at events with control time recorded (minutes)
  slpm                    significant strikes landed per minute
  sapm                    significant strikes absorbed per minute
  sig_acc                 significant strike accuracy, landed / attempted (0-1)
  sig_def                 significant strike defence, 1 - opponents' accuracy (0-1)
  td_avg                  takedowns landed per 15 minutes
  td_rate                 takedowns attempted per 15 minutes
  td_acc                  takedown accuracy, landed / attempted (0-1; NaN with no attempts)
  td_def                  takedown defence, 1 - opponents' accuracy (0-1; NaN with none attempted)
  ctrl_share              own control time / cage time at control-tracked events (0-1)
  ctrl_against_share      opponents' control time / the same cage time (0-1)
  kd_for_per15            knockdowns scored per 15 minutes
  kd_against_per15        knockdowns suffered per 15 minutes
  cum_sig_absorbed        significant strikes absorbed in the career
  cum_head_absorbed       significant strikes absorbed to the head
  cum_kd_against          knockdowns suffered
  grappling_share         (ground + clinch significant strikes landed) / all significant landed (0-1)
  finish_rate_for         share of prior wins by KO/TKO or submission (0-1; NaN with no wins)
  finished_rate_against   share of prior losses by KO/TKO or submission (0-1; NaN with no losses)
  ko_losses_3y            KO/TKO losses in the 3 x 365.25 days before the date
  last_ko_loss_days       days since the most recent KO/TKO loss (NaN if none)
  bouts_3y                bouts in the 3 x 365.25 days before the date
  bouts_per_year          bouts_3y / min(3, UFC tenure in years), tenure floored at 1 year; NaN at debut
  layoff_days             days since the previous bout (NaN at debut)
  ufc_years               years since the first UFC bout (0 at debut)
  age                     age at the date in years, from fighters.csv dob (NaN if unknown)
  win_rate_last5          mean result (win 1, draw 0.5, loss 0) over the last five prior bouts,
                          no contests excluded (NaN with none)
  style                   wrestler, striker, mixed or unknown; see STYLE THRESHOLDS
  bout_*                  the bout's own contribution: bout_result (1 win, 0 loss, 0.5 draw, NaN NC),
                          bout_method, and the raw quantities that roll the cumulative columns forward
                          (bout_win, bout_loss, bout_draw, bout_nc, bout_ko_win, bout_sub_win,
                          bout_ko_loss, bout_sub_loss, bout_minutes, bout_has_stats, bout_stats_minutes,
                          bout_ctrl_tracked, bout_ctrl_minutes, bout_sig_landed, bout_sig_att,
                          bout_sig_absorbed, bout_sig_att_against, bout_td_landed, bout_td_att,
                          bout_td_landed_against, bout_td_att_against, bout_kd, bout_kd_against,
                          bout_ctrl_sec, bout_ctrl_sec_against, bout_head_absorbed, bout_grap_landed)
`features_as_of` adds last_bout_date and as_of; `bout_features` suffixes the columns above with _a
and _b and adds `_diff` (a minus b) for every numeric one.

STYLE THRESHOLDS. Style is read off two wrestling markers that are robust to opponent and division
(takedown attempts and control time; the strike-position mix is noisier, since ground-and-pound
heavyweights post high clinch-plus-ground shares without wrestling). Among the 1,275 fighters with
five or more bouts as of 2026-10-18 the medians are 3.4 attempts per 15 min and 18% control, with
quartiles at 1.7 / 5.6 attempts and 11% / 30% control. The cut points are round numbers at about
those quartiles, so each pure style is roughly the top or bottom quarter on both markers at once:
  wrestler  td_rate >= 5.0 attempts per 15 min and ctrl_share >= 0.25
  striker   td_rate <  2.5 attempts per 15 min and ctrl_share <  0.15
  mixed     everything else with at least one statistical bout
  unknown   no prior bout with statistics
When ctrl_share is NaN (only pre-1999 careers) the control condition is dropped and td_rate decides.
Shares as of 2026-10-18 among the 1,275 fighters with 5+ bouts: 23% wrestler, 30% striker, 47% mixed
(297 / 379 / 599). The thresholds are module constants, so the split can be moved and re-reported.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"

THREE_YEARS = pd.Timedelta(days=3 * 365.25)
DAYS_PER_YEAR = 365.25

WRESTLER_TD_RATE = 5.0     # takedown attempts per 15 min, at or above
WRESTLER_CTRL_SHARE = 0.25  # share of cage time in control, at or above
STRIKER_TD_RATE = 2.5      # takedown attempts per 15 min, below
STRIKER_CTRL_SHARE = 0.15   # share of cage time in control, below

# own-side bout totals carried into the long table (name in bouts_with_stats without the _a/_b suffix)
OWN_STATS = ["kd", "sig_landed", "sig_att", "td_landed", "td_att", "ctrl_sec", "head_landed",
             "clinch_landed", "ground_landed"]
# opponent-side totals carried as *_against
AGAINST_STATS = ["kd", "sig_landed", "sig_att", "td_landed", "td_att", "ctrl_sec", "head_landed"]

ID_COLS = ["fighter", "opponent", "bout_id", "date", "side"]
COUNT_COLS = ["n_bouts", "n_wins", "n_losses", "n_draws", "n_nc", "ko_wins", "sub_wins", "ko_losses", "sub_losses",
              "minutes", "stats_bouts", "stats_minutes", "ctrl_minutes"]
RATE_COLS = ["slpm", "sapm", "sig_acc", "sig_def", "td_avg", "td_rate", "td_acc", "td_def", "ctrl_share",
             "ctrl_against_share", "kd_for_per15", "kd_against_per15", "cum_sig_absorbed", "cum_head_absorbed",
             "cum_kd_against", "grappling_share", "finish_rate_for", "finished_rate_against"]
HISTORY_COLS = ["ko_losses_3y", "last_ko_loss_days", "bouts_3y", "bouts_per_year", "layoff_days", "ufc_years", "age",
                "win_rate_last5"]
NUMERIC_COLS = COUNT_COLS + RATE_COLS + HISTORY_COLS
FEATURE_COLS = NUMERIC_COLS + ["style"]

# per-bout contributions (the bout_* columns, without the prefix)
CONTRIB_COLS = ["win", "loss", "draw", "nc", "ko_win", "sub_win", "ko_loss", "sub_loss", "minutes", "has_stats",
                "stats_minutes", "ctrl_tracked", "ctrl_minutes", "sig_landed", "sig_att", "sig_absorbed",
                "sig_att_against", "td_landed", "td_att", "td_landed_against", "td_att_against", "kd", "kd_against",
                "ctrl_sec", "ctrl_sec_against", "head_absorbed", "grap_landed"]


def load_fighters() -> pd.DataFrame | None:
    """data/processed/fighters.csv if it exists, else None (ages are then NaN)."""
    path = PROC / "fighters.csv"
    return pd.read_csv(path) if path.exists() else None


def _dob(fighters: pd.DataFrame | None) -> pd.Series | None:
    if fighters is None or "dob" not in fighters.columns:
        return None
    f = fighters.drop_duplicates("fighter").set_index("fighter")
    return pd.to_datetime(f["dob"], errors="coerce")


def _long(bouts: pd.DataFrame) -> pd.DataFrame:
    """One row per (fighter, bout) in (date, bout_id, side) order with own and opponents' bout totals."""
    b = bouts.sort_values(["date", "bout_id"], kind="stable").reset_index(drop=True)
    has_stats = b["has_stats"].astype(bool) if "has_stats" in b.columns \
        else (b["sig_att_a"].notna() & b["sig_att_b"].notna())
    ctrl_any = ((b["ctrl_sec_a"].fillna(0) + b["ctrl_sec_b"].fillna(0)) > 0) & has_stats
    ctrl_tracked = ctrl_any.groupby(b["event"]).transform("any") if "event" in b.columns else ctrl_any
    frames = []
    for side, opp in (("a", "b"), ("b", "a")):
        result = b["result_a"] if side == "a" else 1.0 - b["result_a"]
        d = {"fighter": b[f"fighter_{side}"], "opponent": b[f"fighter_{opp}"], "bout_id": b["bout_id"],
             "date": b["date"], "side": side, "result": result.astype(float), "method": b["method"],
             "fight_seconds": b["fight_seconds"].astype(float), "has_stats": has_stats, "ctrl_tracked": ctrl_tracked}
        for c in OWN_STATS:
            d[c] = b[f"{c}_{side}"].astype(float)
        for c in AGAINST_STATS:
            d[f"{c}_against"] = b[f"{c}_{opp}"].astype(float)
        frames.append(pd.DataFrame(d))
    long = pd.concat(frames, ignore_index=True)
    return long.sort_values(["date", "bout_id", "side"], kind="stable").reset_index(drop=True)


def _contributions(L: pd.DataFrame) -> pd.DataFrame:
    """Each row's own contribution to the cumulative columns; bouts without statistics contribute zeros."""
    c = pd.DataFrame(index=L.index)
    res, method, stats = L["result"], L["method"], L["has_stats"].astype(bool)
    c["bout"] = 1
    c["win"] = (res == 1.0).astype(int)
    c["loss"] = (res == 0.0).astype(int)
    c["draw"] = (res == 0.5).astype(int)
    c["nc"] = res.isna().astype(int)
    c["ko_win"] = c["win"] * (method == "KO/TKO").astype(int)
    c["sub_win"] = c["win"] * (method == "SUB").astype(int)
    c["ko_loss"] = c["loss"] * (method == "KO/TKO").astype(int)
    c["sub_loss"] = c["loss"] * (method == "SUB").astype(int)
    c["res"] = res.fillna(0.0)
    c["decided"] = res.notna().astype(int)
    minutes = L["fight_seconds"].fillna(0.0) / 60.0
    c["minutes"] = minutes
    c["has_stats"] = stats.astype(int)
    c["stats_minutes"] = minutes.where(stats, 0.0)
    tracked = L["ctrl_tracked"].astype(bool) & stats
    c["ctrl_tracked"] = tracked.astype(int)
    c["ctrl_minutes"] = minutes.where(tracked, 0.0)

    def own(col: str) -> pd.Series:
        return L[col].where(stats, 0.0).fillna(0.0)

    c["sig_landed"] = own("sig_landed")
    c["sig_att"] = own("sig_att")
    c["sig_absorbed"] = own("sig_landed_against")
    c["sig_att_against"] = own("sig_att_against")
    c["td_landed"] = own("td_landed")
    c["td_att"] = own("td_att")
    c["td_landed_against"] = own("td_landed_against")
    c["td_att_against"] = own("td_att_against")
    c["kd"] = own("kd")
    c["kd_against"] = own("kd_against")
    c["ctrl_sec"] = own("ctrl_sec").where(tracked, 0.0)
    c["ctrl_sec_against"] = own("ctrl_sec_against").where(tracked, 0.0)
    c["head_absorbed"] = own("head_landed_against")
    c["grap_landed"] = own("clinch_landed") + own("ground_landed")
    return c


def _window_before(L: pd.DataFrame, incl: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Inclusive cumulative totals of `cols` at the fighter's last bout dated strictly before date - 3 years."""
    left = pd.DataFrame({"fighter": L["fighter"], "cut": L["date"] - THREE_YEARS, "row": L.index})
    right = pd.DataFrame({"fighter": L["fighter"], "date": L["date"]})
    for c in cols:
        right[c] = incl[c].to_numpy()
    m = pd.merge_asof(left.sort_values("cut", kind="stable"), right.sort_values("date", kind="stable"),
                      left_on="cut", right_on="date", by="fighter", allow_exact_matches=False)
    return m.set_index("row")[cols].reindex(L.index).fillna(0.0)


def _cumulative(L: pd.DataFrame, dob: pd.Series | None) -> pd.DataFrame:
    """Cumulative-before statistics for every row of a long table that is already in chronological order."""
    c = _contributions(L)
    g = L.groupby("fighter", sort=False)
    incl = c.groupby(L["fighter"], sort=False).cumsum()
    # exclusive cumulative = the previous row's inclusive total; a shift (not `incl - c`) keeps it free of
    # floating-point residue, so an as-of row and the next bout's row are bit-identical at any threshold
    before = incl.groupby(L["fighter"], sort=False).shift(1).fillna(0.0)

    out = pd.DataFrame(index=L.index)
    for k in ID_COLS:
        out[k] = L[k]
    out["n_bouts"] = before["bout"].astype(int)
    out["n_wins"] = before["win"].astype(int)
    out["n_losses"] = before["loss"].astype(int)
    out["n_draws"] = before["draw"].astype(int)
    out["n_nc"] = before["nc"].astype(int)
    for k, src in (("ko_wins", "ko_win"), ("sub_wins", "sub_win"), ("ko_losses", "ko_loss"), ("sub_losses", "sub_loss")):
        out[k] = before[src].astype(int)
    out["minutes"] = before["minutes"]
    out["stats_bouts"] = before["has_stats"].astype(int)
    out["stats_minutes"] = before["stats_minutes"]
    out["ctrl_minutes"] = before["ctrl_minutes"]

    sm = before["stats_minutes"].where(before["stats_minutes"] > 0)
    cm = before["ctrl_minutes"].where(before["ctrl_minutes"] > 0)
    no_stats = (before["has_stats"] == 0) & (before["bout"] > 0)   # prior bouts exist but none has statistics

    def ratio(num: pd.Series, den: pd.Series) -> pd.Series:
        return num / den.where(den > 0)

    out["slpm"] = before["sig_landed"] / sm
    out["sapm"] = before["sig_absorbed"] / sm
    out["sig_acc"] = ratio(before["sig_landed"], before["sig_att"])
    out["sig_def"] = 1.0 - ratio(before["sig_absorbed"], before["sig_att_against"])
    out["td_avg"] = before["td_landed"] / sm * 15.0
    out["td_rate"] = before["td_att"] / sm * 15.0
    out["td_acc"] = ratio(before["td_landed"], before["td_att"])
    out["td_def"] = 1.0 - ratio(before["td_landed_against"], before["td_att_against"])
    out["ctrl_share"] = before["ctrl_sec"] / (cm * 60.0)
    out["ctrl_against_share"] = before["ctrl_sec_against"] / (cm * 60.0)
    out["kd_for_per15"] = before["kd"] / sm * 15.0
    out["kd_against_per15"] = before["kd_against"] / sm * 15.0
    out["cum_sig_absorbed"] = before["sig_absorbed"].mask(no_stats)
    out["cum_head_absorbed"] = before["head_absorbed"].mask(no_stats)
    out["cum_kd_against"] = before["kd_against"].mask(no_stats)
    out["grappling_share"] = ratio(before["grap_landed"], before["sig_landed"])
    out["finish_rate_for"] = ratio(before["ko_win"] + before["sub_win"], before["win"])
    out["finished_rate_against"] = ratio(before["ko_loss"] + before["sub_loss"], before["loss"])

    # rolling three-year window: totals before the bout minus totals before (date - 3 years)
    cut = _window_before(L, incl, ["ko_loss", "bout"])
    out["ko_losses_3y"] = (before["ko_loss"] - cut["ko_loss"]).astype(int)
    bouts_3y = (before["bout"] - cut["bout"]).astype(int)
    out["bouts_3y"] = bouts_3y

    # recency: the most recent KO/TKO loss before this bout
    ko_date = L["date"].where(c["ko_loss"] == 1)
    last_ko_before = ko_date.groupby(L["fighter"], sort=False).ffill().groupby(L["fighter"], sort=False).shift(1)
    out["last_ko_loss_days"] = (L["date"] - last_ko_before).dt.days.astype(float)

    first_date = g["date"].transform("first")
    ufc_years = (L["date"] - first_date).dt.days / DAYS_PER_YEAR
    out["bouts_per_year"] = (bouts_3y / ufc_years.clip(lower=1.0, upper=3.0)).where(before["bout"] > 0)
    out["layoff_days"] = (L["date"] - g["date"].shift(1)).dt.days.astype(float)
    out["ufc_years"] = ufc_years
    if dob is not None:
        born = dob.reindex(L["fighter"]).to_numpy()
        out["age"] = (L["date"].to_numpy() - born) / np.timedelta64(1, "D") / DAYS_PER_YEAR
    else:
        out["age"] = np.nan

    # last five prior bouts: sum before the bout minus the sum five bouts earlier
    res5 = before["res"] - before["res"].groupby(L["fighter"], sort=False).shift(5).fillna(0.0)
    dec5 = before["decided"] - before["decided"].groupby(L["fighter"], sort=False).shift(5).fillna(0.0)
    out["win_rate_last5"] = ratio(res5, dec5)

    out["style"] = classify_style(out["td_rate"], out["ctrl_share"], out["stats_bouts"])

    for k in CONTRIB_COLS:
        out[f"bout_{k}"] = c[k]
    out["bout_result"] = L["result"]
    out["bout_method"] = L["method"]
    return out


def classify_style(td_rate: pd.Series, ctrl_share: pd.Series, stats_bouts: pd.Series) -> pd.Series:
    """wrestler / striker / mixed from takedown attempts per 15 min and control share; unknown without statistics.

    A NaN control share (control was not recorded before UFC 21) drops the control condition.
    """
    ctrl_hi = ctrl_share.isna() | (ctrl_share >= WRESTLER_CTRL_SHARE)
    ctrl_lo = ctrl_share.isna() | (ctrl_share < STRIKER_CTRL_SHARE)
    wrestler = (td_rate >= WRESTLER_TD_RATE) & ctrl_hi
    striker = (td_rate < STRIKER_TD_RATE) & ctrl_lo
    labels = np.select([stats_bouts <= 0, wrestler.fillna(False), striker.fillna(False)],
                       ["unknown", "wrestler", "striker"], default="mixed")
    return pd.Series(labels, index=td_rate.index)


def career_table(bouts: pd.DataFrame, fighters: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per (fighter, bout) in chronological order with the fighter's cumulative statistics before
    that bout (zeros / NaN and n_bouts 0 at the debut) and the bout's own contribution as bout_* columns.

    `fighters` supplies dob for age; when None, data/processed/fighters.csv is used if present.
    """
    if fighters is None:
        fighters = load_fighters()
    return _cumulative(_long(bouts), _dob(fighters))


def features_as_of(bouts: pd.DataFrame, as_of: str | pd.Timestamp | np.datetime64,
                   fighters: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every fighter's statistics using only bouts dated strictly before `as_of`, indexed by fighter.

    Layoff, age, UFC tenure and the three-year windows are measured at `as_of`. Fighters with no bout
    before `as_of` are absent. By construction a fighter's row equals the cumulative row of his next bout
    whenever that bout falls on `as_of`.
    """
    as_of = pd.Timestamp(as_of)
    if fighters is None:
        fighters = load_fighters()
    L = _long(bouts[bouts["date"] < as_of])
    cols = FEATURE_COLS + ["last_bout_date", "as_of"]
    if L.empty:
        return pd.DataFrame(columns=cols, index=pd.Index([], name="fighter"))
    names = L["fighter"].drop_duplicates().to_numpy()
    phantom = pd.DataFrame({"fighter": names, "opponent": None, "bout_id": -1,
                            "date": pd.Series(np.full(len(names), as_of), dtype=L["date"].dtype).to_numpy(),
                            "side": "x", "result": np.nan, "method": None, "fight_seconds": 0.0,
                            "has_stats": False, "ctrl_tracked": False})
    for k in OWN_STATS + [f"{k}_against" for k in AGAINST_STATS]:
        phantom[k] = np.nan
    both = pd.concat([L, phantom[L.columns]], ignore_index=True)
    cum = _cumulative(both, _dob(fighters))
    last = L.groupby("fighter", sort=False)["date"].max()
    out = cum[cum["side"] == "x"].set_index("fighter")[FEATURE_COLS].copy()
    out["last_bout_date"] = last.reindex(out.index)
    out["as_of"] = as_of
    return out[cols]


def bout_features(bouts: pd.DataFrame, fighters: pd.DataFrame | None = None) -> pd.DataFrame:
    """Both fighters' pre-fight statistics per bout, indexed by bout_id: `_a`, `_b` and `_diff` (a minus b)
    for the numeric columns, `style_a` and `style_b` for the categorical one. No bout_* outcome columns."""
    ct = career_table(bouts, fighters)
    a = ct[ct["side"] == "a"].set_index("bout_id")
    b = ct[ct["side"] == "b"].set_index("bout_id").reindex(a.index)
    cols = {"date": a["date"], "fighter_a": a["fighter"], "fighter_b": b["fighter"]}
    for k in NUMERIC_COLS:
        cols[f"{k}_a"] = a[k]
        cols[f"{k}_b"] = b[k]
        cols[f"{k}_diff"] = a[k] - b[k]
    cols["style_a"] = a["style"]
    cols["style_b"] = b["style"]
    return pd.DataFrame(cols, index=a.index)


def main() -> None:
    import time

    t0 = time.time()
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    fighters = load_fighters()
    ct = career_table(bouts, fighters)
    t1 = time.time()
    bf = bout_features(bouts, fighters)
    t2 = time.time()
    as_of = bouts["date"].max() + pd.Timedelta(days=1)
    fa = features_as_of(bouts, as_of, fighters)
    t3 = time.time()
    print(f"career_table: {len(ct):,} rows in {t1 - t0:.2f}s; bout_features: {len(bf):,} rows in {t2 - t1:.2f}s; "
          f"features_as_of({as_of.date()}): {len(fa):,} fighters in {t3 - t2:.2f}s")
    vet = fa[fa["n_bouts"] >= 5]
    print(f"\nfighters with 5+ bouts: {len(vet):,}")
    print(vet[["slpm", "sapm", "td_avg", "ctrl_share"]].describe().round(2).to_string())
    print("\nstyle shares (5+ bouts):", vet["style"].value_counts(normalize=True).round(3).to_dict())
    print("corr(sapm, ko_losses):", round(vet[["sapm", "ko_losses"]].corr().iloc[0, 1], 3))


if __name__ == "__main__":
    main()
