"""
rankings.py - Six-dimension composite rankings with adjustable weights.

For every active fighter (last bout inside `active_window_days`) in each
division, compute six dimensions, percentile-rank each one within the
division, and combine with the weights in config/weights.yaml.

Dimensions
  rating        current Elo (performance-adjusted, tuned in backtest.py)
  form_3y       net Elo change over the last 36 months
  entrenchment  0.5 * percentile(UFC bouts) + 0.5 * percentile(top-15 wins)
                where a "top-15 win" is a win over an opponent whose pre-fight
                Elo ranked inside the division's active top 15 on that date
  offense       mean z-score of: sig strikes landed / min, strike differential / min,
                knockdowns / 15 min, takedowns / 15 min, sub attempts / 15 min
                (last 36 months if >= 2 bouts, else career)
  activity      bouts in last 24 months minus a penalty for days since last bout
  durability    mean z-score of: -(sig strikes absorbed / min), -(finish losses per bout)

Also reports rank stability: the 10th-90th percentile of a fighter's rank
across random weight vectors drawn around the configured weights, so a
"No. 7 vs No. 8" argument can be shown for what it is.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.elo import EloParams, run_elo

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs"
CFG = ROOT / "config" / "weights.yaml"

RANKED_DIVISIONS = [
    "Flyweight", "Bantamweight", "Featherweight", "Lightweight", "Welterweight",
    "Middleweight", "Light Heavyweight", "Heavyweight",
    "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight",
]


def load_cfg() -> dict:
    return yaml.safe_load(CFG.read_text())


def long_bouts(rated: pd.DataFrame) -> pd.DataFrame:
    """One row per fighter per bout, with own and opponent stats."""
    stat_cols = ["kd", "sig_landed", "sig_att", "td_landed", "sub_att", "ctrl_sec"]
    base = ["bout_id", "date", "event", "division", "method", "finish", "minutes", "has_stats", "title_fight"]
    a = rated[base + ["fighter_a", "fighter_b", "result_a", "elo_pre_a", "elo_pre_b", "elo_post_a"]
              + [f"{c}_a" for c in stat_cols] + [f"{c}_b" for c in stat_cols]].copy()
    a.columns = base + ["fighter", "opponent", "result", "elo_pre", "opp_elo_pre", "elo_post"] \
        + stat_cols + [f"opp_{c}" for c in stat_cols]
    b = rated[base + ["fighter_b", "fighter_a", "result_a", "elo_pre_b", "elo_pre_a", "elo_post_b"]
              + [f"{c}_b" for c in stat_cols] + [f"{c}_a" for c in stat_cols]].copy()
    b.columns = a.columns
    b["result"] = 1 - b["result"]
    df = pd.concat([a, b], ignore_index=True)
    df = df[df["result"].notna()]           # drop no-contests
    df["win"] = (df["result"] == 1.0).astype(int)
    df["loss"] = (df["result"] == 0.0).astype(int)
    df["finish_loss"] = ((df["result"] == 0.0) & df["finish"]).astype(int)
    return df.sort_values(["date", "bout_id"]).reset_index(drop=True)


def top15_win_flags(lb: pd.DataFrame, hist: pd.DataFrame, window_days: int) -> pd.Series:
    """Was the opponent inside the division's active top-15 (by Elo) on the bout date?"""
    flags = pd.Series(False, index=lb.index)
    hist = hist.sort_values(["date", "bout_id"])
    for date, grp in lb.groupby("date"):
        before = hist[hist["date"] < date]
        active = before[before["date"] >= date - pd.Timedelta(days=window_days)]
        latest = before.groupby("fighter").tail(1).set_index("fighter")
        active_names = set(active["fighter"])
        latest = latest[latest.index.isin(active_names)]
        for div, g in grp.groupby("division"):
            pool = latest[latest["division"] == div]["rating"].sort_values(ascending=False)
            top = set(pool.head(15).index)
            idx = g.index[g["opponent"].isin(top) & (g["win"] == 1)]
            flags.loc[idx] = True
    return flags


def zmean(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    z = (df[cols] - df[cols].mean()) / df[cols].std(ddof=0).replace(0, 1)
    return z.mean(axis=1)


def build_features(rated: pd.DataFrame, hist: pd.DataFrame, cfg: dict, as_of: pd.Timestamp) -> pd.DataFrame:
    lb = long_bouts(rated)
    lb = lb[lb["date"] <= as_of]
    lb["top15_win"] = top15_win_flags(lb, hist, cfg["active_window_days"])

    last = lb.groupby("fighter").tail(1).set_index("fighter")
    # division: "latest" = division of the most recent ranked-division bout (how the
    # UFC re-slots movers, e.g. Costa and de Ridder to light heavyweight);
    # "mode3" = most common of the last three, ties to the most recent
    ranked = lb[lb["division"].isin(RANKED_DIVISIONS)]
    if cfg.get("division_rule", "latest") == "mode3":
        last3 = ranked.groupby("fighter").tail(3)

        def pick_div(g: pd.DataFrame) -> str:
            counts = g["division"].value_counts()
            top = counts[counts == counts.max()].index
            return g.iloc[-1]["division"] if len(top) > 1 else top[0]

        last_div = last3.groupby("fighter").apply(pick_div, include_groups=False)
    else:
        last_div = ranked.groupby("fighter").tail(1).set_index("fighter")["division"]

    cutoff_3y = as_of - pd.Timedelta(days=3 * 365)
    cutoff_2y = as_of - pd.Timedelta(days=2 * 365)
    lb["prior_bouts"] = lb.groupby("fighter").cumcount()
    recent = lb[lb["date"] >= cutoff_3y]
    recent_form = recent[recent["prior_bouts"] >= 2]      # form ignores the first two UFC bouts

    g_all = lb.groupby("fighter")
    g_rec = recent.groupby("fighter")
    g_form = recent_form.groupby("fighter")

    f = pd.DataFrame(index=last.index)
    f["division"] = last_div.reindex(f.index)
    # last appearance counts no-contests too (a fighter who had an NC last month is active)
    appearances = pd.concat([rated[["date", "fighter_a"]].rename(columns={"fighter_a": "fighter"}),
                             rated[["date", "fighter_b"]].rename(columns={"fighter_b": "fighter"})])
    appearances = appearances[appearances["date"] <= as_of]
    f["last_fight"] = appearances.groupby("fighter")["date"].max().reindex(f.index)
    f["days_since"] = (as_of - f["last_fight"]).dt.days
    f["rating"] = last["elo_post"]
    f["ufc_bouts"] = g_all.size()
    f["wins"] = g_all["win"].sum()
    f["losses"] = g_all["loss"].sum()
    f["top15_wins"] = g_all["top15_win"].sum()

    # form: net Elo over last 3 years (rating now minus rating carried into first bout in window)
    first_rec = g_form.head(1).set_index("fighter")["elo_pre"]
    f["form_3y"] = (f["rating"] - first_rec.reindex(f.index)).fillna(0.0)
    f["bouts_3y"] = g_rec.size().reindex(f.index).fillna(0)
    f["record_3y"] = (g_rec["win"].sum().reindex(f.index).fillna(0).astype(int).astype(str) + "-"
                      + g_rec["loss"].sum().reindex(f.index).fillna(0).astype(int).astype(str))

    # offense / durability: last 3 years if >=2 bouts with stats, else career
    RATE_KEYS = ["slpm", "sapm", "diff_pm", "kd_p15", "td_p15", "sub_p15", "finish_loss_rate"]

    def rates(g: pd.DataFrame) -> pd.Series:
        g = g[g["has_stats"]]
        mins = g["minutes"].sum()
        if mins <= 0:
            return pd.Series({k: np.nan for k in RATE_KEYS})
        return pd.Series({
            "slpm": g["sig_landed"].sum() / mins,
            "sapm": g["opp_sig_landed"].sum() / mins,
            "diff_pm": (g["sig_landed"].sum() - g["opp_sig_landed"].sum()) / mins,
            "kd_p15": 15 * g["kd"].sum() / mins,
            "td_p15": 15 * g["td_landed"].sum() / mins,
            "sub_p15": 15 * g["sub_att"].sum() / mins,
            "finish_loss_rate": g["finish_loss"].sum() / max(len(g), 1),
        })

    career = g_all.apply(rates, include_groups=False)
    rec = g_rec.apply(rates, include_groups=False)
    use_recent = (f["bouts_3y"] >= 2)
    stats = career.copy()
    rec = rec.reindex(stats.index)
    for c in stats.columns:
        stats.loc[use_recent & rec[c].notna(), c] = rec.loc[use_recent & rec[c].notna(), c]
    f = f.join(stats)

    f["bouts_2y"] = lb[lb["date"] >= cutoff_2y].groupby("fighter").size().reindex(f.index).fillna(0)
    # activity: bouts in 24 months, minus 1 point per 180 days of inactivity beyond 180
    f["activity"] = f["bouts_2y"] - np.clip((f["days_since"] - 180) / 180.0, 0, None)

    # eligibility
    f = f[(f["days_since"] <= cfg["active_window_days"]) & (f["ufc_bouts"] >= cfg["min_ufc_bouts"])]
    f = f[f["division"].isin(RANKED_DIVISIONS)]
    # fighters no longer on the UFC roster (released, retired) as of the board date; bout data cannot see this
    from mmalab.resume_board import exclusions_as_of      # local import: resume_board imports this module
    f = f[~f.index.isin(exclusions_as_of(as_of))]
    return f.reset_index().rename(columns={"index": "fighter"})


def _parse_override(v) -> tuple[str, pd.Timestamp | None]:
    """'Name' or 'VACANT', optionally followed by 'since YYYY-MM-DD' (the date the entry took effect)."""
    m = re.match(r"^(.*?)\s+since\s+(\d{4}-\d{2}-\d{2})\s*$", str(v).strip())
    return (m.group(1).strip(), pd.Timestamp(m.group(2))) if m else (str(v).strip(), None)


def champions(rated: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, str]:
    """Winner of the most recent undisputed UFC title bout in each division.

    config/champions_override.yaml covers what bout data cannot see (a vacated belt, an
    interim champion promoted). An override only stands until the next undisputed title
    bout in its division: once the data holds a title bout dated after the override's
    'since' date, the bout result wins and the stale override is reported, so a belt
    filled in the cage can never stay VACANT on the board.
    """
    t = rated[rated["title_fight"] & ~rated["interim"] & (rated["date"] <= as_of)
              & rated["result_a"].isin([0.0, 1.0]) & rated["division"].isin(RANKED_DIVISIONS)]
    champs, last_title = {}, {}
    for div, g in t.sort_values("date").groupby("division"):
        row = g.iloc[-1]
        champs[div] = row["fighter_a"] if row["result_a"] == 1.0 else row["fighter_b"]
        last_title[div] = row["date"]
    override = ROOT / "config" / "champions_override.yaml"
    if override.exists():
        for k, v in (yaml.safe_load(override.read_text()) or {}).items():
            holder, since = _parse_override(v)
            if since is None:
                raise ValueError(f"champions_override.yaml: '{k}' needs a date, e.g. '{holder} since YYYY-MM-DD', "
                                 "so a later title bout can supersede it")
            if since > as_of:
                continue                         # not yet in effect on this date
            if k in last_title and last_title[k] > since:
                print(f"[champions] override '{k}: {v}' superseded by the title bout of "
                      f"{last_title[k].date()} ({champs[k]}); remove it from champions_override.yaml")
                continue
            if holder.upper() == "VACANT":
                champs.pop(k, None)
            else:
                champs[k] = holder
    return champs


def composite(f: pd.DataFrame, weights: dict) -> pd.DataFrame:
    f = f.copy()
    out = []
    for div, g in f.groupby("division"):
        g = g.copy()
        pct = lambda s: s.rank(pct=True, method="average")
        g["p_rating"] = pct(g["rating"])
        g["p_form"] = pct(g["form_3y"])
        g["p_entrench"] = 0.5 * pct(g["ufc_bouts"]) + 0.5 * pct(g["top15_wins"])
        g["p_offense"] = pct(zmean(g, ["slpm", "diff_pm", "kd_p15", "td_p15", "sub_p15"]))
        g["p_activity"] = pct(g["activity"])
        g["p_durability"] = pct(zmean(g.assign(neg_sapm=-g["sapm"], neg_fl=-g["finish_loss_rate"]),
                                      ["neg_sapm", "neg_fl"]))
        g["score"] = (weights["rating"] * g["p_rating"] + weights["form_3y"] * g["p_form"]
                      + weights["entrenchment"] * g["p_entrench"] + weights["offense"] * g["p_offense"]
                      + weights["activity"] * g["p_activity"] + weights["durability"] * g["p_durability"])
        g["rank"] = g["score"].rank(ascending=False, method="first").astype(int)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def rank_stability(f: pd.DataFrame, weights: dict, draws: int, conc: float, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    keys = list(weights)
    base = np.array([weights[k] for k in keys])
    ranks = []
    for _ in range(draws):
        w = rng.dirichlet(base * conc)
        r = composite(f, dict(zip(keys, w)))[["fighter", "division", "rank"]]
        ranks.append(r)
    allr = pd.concat(ranks)
    return allr.groupby(["fighter", "division"])["rank"].quantile([0.1, 0.9]).unstack() \
        .rename(columns={0.1: "rank_p10", 0.9: "rank_p90"}).reset_index()


def main(as_of: str | None = None) -> None:
    cfg = load_cfg()
    w = cfg["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6, "weights must sum to 1"
    bouts = pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])
    params = EloParams(**cfg["elo"])
    rated, hist = run_elo(bouts, params)
    as_of_ts = pd.Timestamp(as_of) if as_of else bouts["date"].max()

    feats = build_features(rated, hist, cfg, as_of_ts)
    board = composite(feats, w)
    stab = rank_stability(feats, w, cfg["stability_draws"], cfg["stability_concentration"])
    board = board.merge(stab, on=["fighter", "division"], how="left")
    champs = champions(rated, as_of_ts)
    board["champion"] = board.apply(lambda r: champs.get(r["division"]) == r["fighter"], axis=1)

    # Champions sit above the numbered board (rank 0); contenders are numbered
    # without them, the way the official boards read. rank_all / rank_p10 /
    # rank_p90 keep the champion in the ordering and describe stability.
    board["rank_all"] = board["rank"]
    board = board.sort_values(["division", "rank_all"])
    board["rank"] = board.groupby("division").cumcount() + 1
    champ_rows = board["champion"]
    board["rank"] = board["rank"] - board.groupby("division")["champion"].cumsum().astype(int)
    board.loc[champ_rows, "rank"] = 0

    OUT.mkdir(exist_ok=True)
    board.to_csv(OUT / "composite_rankings_full.csv", index=False)

    top = board[board["rank"] <= cfg["board_size"]]
    show = ["division", "rank", "fighter", "champion", "rank_all", "rank_p10", "rank_p90", "score", "rating",
            "record_3y", "ufc_bouts", "top15_wins", "days_since", "slpm", "diff_pm"]
    top[show].round(3).to_csv(OUT / "composite_top15_by_division.csv", index=False)

    lines = [f"# Composite boards as of {as_of_ts.date()}",
             f"weights: {w}",
             "stability = 10th-90th percentile position (champion included) across "
             f"{cfg['stability_draws']} random weight vectors near the configured weights\n"]
    for div in RANKED_DIVISIONS:
        g = top[top["division"] == div]
        if g.empty:
            continue
        lines.append(f"\n## {div}")
        for r in g.itertuples():
            label = " C" if r.champion else f"{r.rank:>2}"
            band = f"[{int(r.rank_p10)}-{int(r.rank_p90)}]"
            lines.append(f"{label}. {r.fighter:<26} score {r.score:.3f}  elo {r.rating:6.0f}  "
                         f"3y {r.record_3y:<5} bouts {int(r.ufc_bouts):>2}  top15W {int(r.top15_wins)}  "
                         f"days {int(r.days_since):>3}  stability {band}")
        if div not in champs:
            lines.append("    (title vacant)")
        elif not g["champion"].any():
            lines.append(f"    (champion {champs[div]} is outside the active window or unranked)")
    (OUT / "composite_boards.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
