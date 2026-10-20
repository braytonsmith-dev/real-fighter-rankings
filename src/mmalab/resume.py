"""
resume.py - Resume-first rating engine (who has earned it as of now).

Differences from the predictive Elo in elo.py:
  1. Decisions blend the judges' cards with the fight stats (card_weight = 0.5).
     Cards, per judge by point margin: 1 point (29-28, 48-47) = close, 0.6;
     2 points = 0.8; 3+ points (30-27, 49-46, 50-45) = 1.0; mean of three.
     Stats: logistic of the winner's dominance per minute. The official winner
     never scores below a draw, so a robbery (e.g. Jones-Reyes) earns the winner
     little and costs the loser little. Finishes score 1.0.
     "Dominant" needs the cards (2 of 3 at 3+ points) and the stats to agree.
  2. Loss protection, for losses to a division top-3 fighter or in a title fight:
       not dominant                      -> 15% of the normal drop
       dominant (2 of 3 cards 3+ points,
       or a round-one finish)            -> 75%
       round-one finish by a heavy
       favorite (>= 75% pre-fight)       -> 100%
     A loss right after another loss keeps at least 60% (streaks are not one-offs).
     A finish counts as dominant in round one, or early (first half of the scheduled
     rounds) when the loser was clearly behind on stats. A later finish of a fighter
     who was close on stats (winner ahead by 1.5 per minute or less) is a war.
  2b. Proof of concept: a close loss (split/majority decision, a decision scored
     0.70 or less, or a war finish) to a top-5 fighter by someone outside the top 5
     earns the loser a small gain (10% of K) instead of a loss.
  2c. A first-round finish by the underdog moves both ratings only 70% as much.
  3. No rating decay for layoffs. Inactivity is handled separately, with an
     injury exemption (config/layoffs.yaml).
  4. Records quality wins as they happen: opponent had >= 5 UFC wins, or was
     inside the division top 7 at fight time. Five or more = "entrenched".

Positions at fight time are computed from this same rating among fighters
active in the prior `active_days` in that division.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from mmalab.official_ranks import OfficialRanks

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

_CARD = re.compile(r"(\d+)\s*-\s*(\d+)")
EVENT_ALIASES = {
    "UFC Fight Night: Grasso vs. Shevchenko 2": "Noche UFC: Grasso vs. Shevchenko 2",
    "UFC Fight Night: Lopes vs. Silva": "Noche UFC: Lopes vs. Silva",
}


@dataclass
class ResumeParams:
    k: float = 60.0
    k_new_mult: float = 1.5
    n_new: int = 5
    protected_loss_mult: float = 0.15    # top-3 / title-fight loss that was not dominant
    dominant_loss_mult: float = 0.75     # top-3 / title-fight loss that was dominant
    heavy_favorite_p: float = 0.75       # winner's pre-fight win probability (about 3-1)
    consecutive_loss_mult: float = 0.6   # protection is weaker when the previous bout was also a loss
    protection_ladder: tuple | None = None  # v1.1 option: multiplier for a protected non-dominant loss by the number of
                                            # losses among the fighter's previous four bouts, e.g. (0.3, 0.6, 1.0): the
                                            # first loss in a run is protected, the third is not. None = v1.0 rule.
    no_card_decision_s: float = 0.75
    card_weight: float = 0.5             # decisions: share of the score from the judges; the rest from fight stats
    stat_scale: float = 2.0              # dominance per minute that maps to ~73% on the stats side
    dominant_stat_min: float = 0.0       # stats must not contradict the cards (winner not behind on stats)
    war_stat_max: float = 1.5            # a finish counts as a war if the winner was not ahead by more than this per minute
    close_s: float = 0.70                # decisions scored at or below this are close
    proof_top_n: int = 5                 # close fights with a top-5 fighter by someone outside the top 5
    proof_gain: float = 0.10             # ...earn the loser this share of K instead of a loss
    upset_quick_finish_mult: float = 0.7 # R1 finish by the underdog moves both ratings 70% as much
    use_official_ranks: bool = True      # official media-panel rank at fight time (2013+); model position before
    qw_tiers: tuple = ((0, 2.0), (5, 1.5), (10, 1.0), (15, 0.5))   # opponent rank limit -> quality-win value
    qw_veteran_min_wins: int = 8         # unranked opponent with 8+ UFC wins and a winning UFC record...
    qw_veteran_value: float = 0.25       # ...is worth this much
    short_notice_win_mult: float = 1.2
    short_notice_loss_mult: float = 0.5
    protect_top_n: int = 3
    quality_top_n: int = 7
    quality_min_wins: int = 5
    active_days: int = 540
    start: float = 1500.0

    def to_dict(self) -> dict:
        return asdict(self)


def judge_value(m: int) -> float:
    """Winner's score from one judge's point margin. 1 point (29-28, 48-47) is close,
    3+ points (30-27, 49-46, 50-45) is a clear, dominant round split."""
    return {3: 1.0, 2: 0.8, 1: 0.6, 0: 0.5, -1: 0.4, -2: 0.2}.get(max(-3, min(3, m)), 0.0 if m < 0 else 1.0)


def load_scorecards() -> pd.DataFrame:
    r = pd.read_csv(RAW / "ufc_fight_results.csv")
    r.columns = [c.strip() for c in r.columns]
    r = r[r["METHOD"].astype(str).str.strip().str.startswith("Decision")].copy()
    r["bout_url"] = r["URL"]
    r = r.drop_duplicates(subset="bout_url", keep="first")
    r["cards"] = r["DETAILS"].fillna("").astype(str).apply(_CARD.findall)

    def score(cards_raw):
        cards = [(int(a), int(b)) for a, b in cards_raw]
        if len(cards) != 3:
            return (np.nan, False, "")
        diffs = [a - b for a, b in cards]
        sign = np.sign(sum(np.sign(d) for d in diffs))   # the majority orientation is the winner
        if sign == 0:
            return (0.5, False, "")
        margins = [int(sign * d) for d in diffs]
        s_win = float(np.mean([judge_value(m) for m in margins]))
        dominant = sum(m >= 3 for m in margins) >= 2       # 2 of 3 cards at 49-46 / 30-27 or wider
        return (s_win, dominant, ",".join(str(m) for m in margins))

    out = r["cards"].apply(score)
    r["card_s"] = [o[0] for o in out]
    r["card_dominant"] = [o[1] for o in out]
    r["card_margins"] = [o[2] for o in out]
    return r[["bout_url", "card_s", "card_dominant", "card_margins"]]


def apply_overturned(df: pd.DataFrame) -> pd.DataFrame:
    """A no-contest caused by a failed drug test counts as a loss for the fighter who failed
    (UFCStats records 'Failed Drug Test by <name>' in the bout details)."""
    r = pd.read_csv(RAW / "ufc_fight_results.csv")
    r.columns = [c.strip() for c in r.columns]
    det = r.drop_duplicates("URL").set_index("URL")["DETAILS"].fillna("").astype(str)
    df = df.copy()
    df["overturned_by"] = ""
    for i, row in df[df["result_a"].isna()].iterrows():
        text = det.get(row["bout_url"], "")
        m = re.search(r"Failed Drug Test by ([A-Za-z' .-]+?)(?=[A-Z][a-z]+ [A-Z][a-z]* ?\d|$)", text)
        if not m:
            continue
        who = m.group(1).strip().lower()
        a_last, b_last = row["fighter_a"].split()[-1].lower(), row["fighter_b"].split()[-1].lower()
        if who.endswith(a_last) and not who.endswith(b_last):
            df.at[i, "result_a"], df.at[i, "overturned_by"] = 0.0, row["fighter_a"]
        elif who.endswith(b_last) and not who.endswith(a_last):
            df.at[i, "result_a"], df.at[i, "overturned_by"] = 1.0, row["fighter_b"]
        if df.at[i, "overturned_by"]:
            df.at[i, "method"] = "DQ"
    return df


def load_short_notice() -> set:
    p = ROOT / "config" / "short_notice.yaml"
    if not p.exists():
        return set()
    data = yaml.safe_load(p.read_text()) or []
    out = set()
    for item in data:
        out.add((item["fighter"], pd.Timestamp(item["date"]).date()))
    return out


def run_resume(bouts: pd.DataFrame, p: ResumeParams | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = p or ResumeParams()
    cards = load_scorecards()
    df = bouts.merge(cards, on="bout_url", how="left").sort_values(["date", "bout_id"]).reset_index(drop=True)
    df = apply_overturned(df)
    names = pd.concat([df["fighter_a"], df["fighter_b"]]).dropna().unique().tolist()
    official = OfficialRanks(names) if p.use_official_ranks else None
    short_notice = load_short_notice()
    losses: dict[str, int] = {}

    rating: dict[str, float] = {}
    n_fights: dict[str, int] = {}
    wins: dict[str, int] = {}
    last_date: dict[str, pd.Timestamp] = {}
    last_div: dict[str, str] = {}
    last_result: dict[str, str] = {}
    recent_results: dict[str, list] = {}       # last four W/L marks per fighter, for the protection ladder
    active_days = pd.Timedelta(days=p.active_days)

    # per-division index keeps position() cheap
    div_members: dict[str, set] = {}

    def position_fast(name: str, div: str, date: pd.Timestamp) -> int:
        r0 = rating.get(name, p.start)
        better = 0
        for f in div_members.get(div, ()):
            if f != name and date - last_date[f] <= active_days and rating[f] > r0:
                better += 1
        return better + 1

    rows, hist = [], []
    for row in df.itertuples(index=False):
        a, b, d, div = row.fighter_a, row.fighter_b, row.date, row.division
        ra, rb = rating.get(a, p.start), rating.get(b, p.start)
        pos_a = position_fast(a, div, d) if a in rating else 999
        pos_b = position_fast(b, div, d) if b in rating else 999
        # official media-panel rank going in (0 = champion, 99 = unranked); model position before 2013
        off_a = official.rank(a, div, d) if official is not None else None
        off_b = official.rank(b, div, d) if official is not None else None
        eff_a = off_a if off_a is not None else pos_a
        eff_b = off_b if off_b is not None else pos_b
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        res = row.result_a
        rec = {"bout_id": row.bout_id, "pos_a": pos_a, "pos_b": pos_b, "r_pre_a": ra, "r_pre_b": rb,
               "rank_a": eff_a, "rank_b": eff_b, "official_a": off_a, "official_b": off_b,
               "qw_value": 0.0, "top10_win": False, "top15_win": False, "short_notice": "",
               "wins_pre_a": wins.get(a, 0), "wins_pre_b": wins.get(b, 0),
               "s_a": np.nan, "protected": "", "loss_mult": 1.0, "dominant": False,
               "decisive_loss": False, "quality_win": False, "proof": False, "close": False,
               "upset_quick_finish": False, "winner_pos": np.nan, "loser_pos": np.nan}
        if pd.isna(res):
            rows.append({**rec, "r_post_a": ra, "r_post_b": rb})
            continue

        finish = row.method in ("KO/TKO", "SUB")
        if res == 0.5:
            s_win = 0.5
        elif finish:
            s_win = 1.0
        else:
            # decision: blend the judges with the fight stats, never below a draw for the official winner
            dom_w = row.dominance_a if res == 1.0 else -row.dominance_a
            stat_s = 1.0 / (1.0 + np.exp(-dom_w / p.stat_scale)) if not pd.isna(dom_w) else np.nan
            card_s = row.card_s
            if pd.isna(card_s) and pd.isna(stat_s):
                s_win = p.no_card_decision_s
            elif pd.isna(card_s):
                s_win = stat_s
            elif pd.isna(stat_s):
                s_win = float(card_s)
            else:
                s_win = p.card_weight * float(card_s) + (1 - p.card_weight) * stat_s
            s_win = float(np.clip(s_win, 0.5, 1.0))
        sa = s_win if res == 1.0 else (1 - s_win if res == 0.0 else 0.5)

        ka = p.k * (p.k_new_mult if n_fights.get(a, 0) < p.n_new else 1.0)
        kb = p.k * (p.k_new_mult if n_fights.get(b, 0) < p.n_new else 1.0)
        da, db = ka * (sa - ea), kb * ((1 - sa) - (1 - ea))

        # how the loss is treated
        r1_finish = finish and row.round == 1
        dom_winner = (row.dominance_a if res == 1.0 else -row.dominance_a) if res in (0.0, 1.0) else np.nan
        stats_agree = pd.isna(dom_winner) or dom_winner >= p.dominant_stat_min
        # finished while losing the fight = dominant; finished late while even or ahead = a war
        sched = row.sched_rounds if not pd.isna(row.sched_rounds) else 3
        early = (not pd.isna(row.round)) and row.round <= max(1, int(sched) // 2)
        behind = pd.isna(dom_winner) or dom_winner > p.war_stat_max
        finished_while_behind = finish and not r1_finish and early and behind
        war_finish = finish and not r1_finish and not behind
        dominant = bool(r1_finish or finished_while_behind
                        or (not finish and row.card_dominant is True and stats_agree))
        close = bool(war_finish or (not finish and (row.method in ("S-DEC", "M-DEC") or s_win <= p.close_s)))
        rec["s_win"] = s_win if res in (0.0, 1.0) else np.nan
        rec["dominant"] = dominant if res in (0.0, 1.0) else False
        rec["close"] = close if res in (0.0, 1.0) else False
        if res in (0.0, 1.0):
            loser = "a" if res == 0.0 else "b"
            winner_pos = eff_b if loser == "a" else eff_a
            loser_pos = eff_a if loser == "a" else eff_b
            p_winner = (1 - ea) if loser == "a" else ea
            protected_ctx = bool(row.title_fight) or winner_pos <= p.protect_top_n
            k_loser = ka if loser == "a" else kb
            if close and winner_pos <= p.proof_top_n and loser_pos > p.proof_top_n:
                # proof of concept: a close fight with a top-5 fighter shows you belong
                gain = k_loser * p.proof_gain
                if loser == "a":
                    da = gain
                else:
                    db = gain
                rec["proof"] = True
                rec["loss_mult"] = 0.0
            elif protected_ctx:
                if r1_finish and p_winner >= p.heavy_favorite_p:
                    mult = 1.0                    # the real gap: a heavy favorite finished it in round one
                elif dominant:
                    mult = p.dominant_loss_mult
                else:
                    mult = p.protected_loss_mult
                    loser_name = a if loser == "a" else b
                    if p.protection_ladder:
                        # protection is for an isolated loss: it shrinks with every loss among the previous four bouts
                        n_prev = sum(1 for x in recent_results.get(loser_name, []) if x == "L")
                        ladder = tuple(p.protection_ladder)
                        mult = max(mult, float(ladder[min(n_prev, len(ladder) - 1)]))
                    elif last_result.get(loser_name) == "L":
                        mult = max(mult, p.consecutive_loss_mult)   # a losing streak is not a one-off
                if loser == "a" and da < 0:
                    da *= mult
                if loser == "b" and db < 0:
                    db *= mult
                rec["protected"] = loser
                rec["loss_mult"] = mult
            # a quick first-round upset can be a fluke: move both fighters less
            if r1_finish and p_winner < 0.5:
                da *= p.upset_quick_finish_mult
                db *= p.upset_quick_finish_mult
                rec["upset_quick_finish"] = True
            rec["decisive_loss"] = dominant and not rec.get("proof", False)
            rec["winner_pos"], rec["loser_pos"] = winner_pos, loser_pos

        # short notice: a win counts more, a loss costs less
        for side, name in (("a", a), ("b", b)):
            if (name, d.date()) in short_notice:
                rec["short_notice"] += side
                won = (res == 1.0) == (side == "a") and res in (0.0, 1.0)
                delta = da if side == "a" else db
                if won and delta > 0:
                    delta *= p.short_notice_win_mult
                elif not won and delta < 0:
                    delta *= p.short_notice_loss_mult
                if side == "a":
                    da = delta
                else:
                    db = delta

        # quality win bookkeeping: tiered by the opponent's rank going in
        if res in (0.0, 1.0):
            opp_rank = eff_b if res == 1.0 else eff_a
            opp = b if res == 1.0 else a
            value = 0.0
            for limit, v in p.qw_tiers:
                if opp_rank <= limit:
                    value = v
                    break
            if value == 0.0 and wins.get(opp, 0) >= p.qw_veteran_min_wins and wins.get(opp, 0) > losses.get(opp, 0):
                value = p.qw_veteran_value          # unranked, but a proven UFC winner
            rec["qw_value"] = value
            rec["quality_win"] = value > 0
            rec["top10_win"] = opp_rank <= 10
            rec["top15_win"] = opp_rank <= 15

        na, nb = ra + da, rb + db
        rating[a], rating[b] = na, nb
        for f, won in ((a, res == 1.0), (b, res == 0.0)):
            n_fights[f] = n_fights.get(f, 0) + 1
            wins[f] = wins.get(f, 0) + int(won)
            losses[f] = losses.get(f, 0) + int(res in (0.0, 1.0) and not won)
            last_result[f] = "W" if won else ("L" if res in (0.0, 1.0) else "D")
            if res in (0.0, 1.0):
                recent_results[f] = (recent_results.get(f, []) + ["W" if won else "L"])[-4:]
            if last_div.get(f) != div and f in last_div:
                div_members.get(last_div[f], set()).discard(f)
            last_div[f], last_date[f] = div, d
            div_members.setdefault(div, set()).add(f)
        rec.update({"s_a": sa, "r_post_a": na, "r_post_b": nb})
        rows.append(rec)
        hist.append((a, d, row.bout_id, div, na))
        hist.append((b, d, row.bout_id, div, nb))

    out = df.merge(pd.DataFrame(rows), on="bout_id", how="left")
    h = pd.DataFrame(hist, columns=["fighter", "date", "bout_id", "division", "rating"])
    return out, h
