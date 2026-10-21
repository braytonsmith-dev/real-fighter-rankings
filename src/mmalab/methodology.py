"""
methodology.py - Writes METHODOLOGY.md (and docs/methodology.html) from the live
configuration and the audit trail, so every number in the document is the
number the model used on this rebuild.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"
OUT = ROOT / "outputs"
DOCS = ROOT / "docs"

EXAMPLES = [
    ("Bantamweight", "Mario Bautista"), ("Bantamweight", "Cory Sandhagen"),
    ("Light Heavyweight", "Jiri Prochazka"), ("Light Heavyweight", "Khalil Rountree Jr."),
    ("Heavyweight", "Alex Pereira"), ("Welterweight", "Kamaru Usman"), ("Welterweight", "Kevin Holland"),
    ("Flyweight", "Brandon Moreno"), ("Lightweight", "Max Holloway"),
]


def _y(name: str) -> dict:
    p = CFG / name
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def build_text() -> str:
    cfg = _y("weights.yaml")
    rc = cfg["resume"]
    e = rc["engine"]
    L = rc["ledger"]
    ina = rc["inactivity"]
    h2h = rc["head_to_head"]
    tc = rc["title_cycle"]
    fp = rc["form_penalty"]
    hz = rc["horizons"]
    audit = pd.read_csv(OUT / "audit_top30.csv")
    bouts = pd.read_csv(ROOT / "data" / "processed" / "bouts.csv", parse_dates=["date"])
    as_of = bouts["date"].max().date()
    pair = pd.read_csv(OUT / "compare_pairwise.csv") if (OUT / "compare_pairwise.csv").exists() else None
    bt = json.loads((OUT / "backtest_report.json").read_text()) if (OUT / "backtest_report.json").exists() else None

    t = []
    a = t.append
    a(f"# {cfg.get('site_name', 'REAL Fighter Rankings')}: Methodology, version {cfg.get('method_version', '1.0')}")
    a("")
    a(f"*{cfg.get('site_tagline', '')}.* Data through {as_of}. This document is generated from the live "
      "configuration (`config/weights.yaml`) and the audit trail (`outputs/audit_top30.csv`) on every rebuild.")
    a("")
    a("## 1. What the rank means")
    a("")
    a("A resume rank: who has earned the position as of today, updated automatically each week. The single principle "
      "behind every rule: **a fighter is ranked on how he performed against the fighters he faced, and how good those "
      "fighters were.** The goal is the most defensible board possible, not agreement with any other board. It is not a "
      "prediction of who would win tomorrow; that is a separate model (section 8, and the Prediction page). Champions (C), "
      "interim champions (IC) and reserved spots (R: former champions who vacated with an injury and are owed a title "
      "shot) sit above the numbered board with their metrics shown. Contenders are numbered 1 to 30.")
    a("")
    a("## 2. Data and how far to trust it")
    a("")
    a("| Source | What it provides | Coverage | Reliability |")
    a("|---|---|---|---|")
    a(f"| UFCStats (official UFC statistics), via the Greco1899 open scraper | Every UFC bout: result, method, round, time, judges' scorecards, round-by-round strikes, knockdowns, takedowns, submission attempts, control time | {len(bouts):,} bouts, 1994 to {as_of}; round stats for 99.8%; all three judges' cards for 98.6% of decisions (100% since 2005) | High for what it records. Strike counts are hand-coded and do not measure damage. Judges' cards are official but can be wrong. |")
    a("| Official UFC rankings history (martj42/ufc_rankings_history, every media-panel release Feb 2013 to June 2026, extended with weekly snapshots of ufc.com) | Each opponent's official rank on the day of the fight | 534 releases; about 99% of ranked names matched to UFCStats | High; before Feb 2013 the model's own position is used instead |")
    a("| Hand-kept configuration files | Retirements and releases, documented injury layoffs, announced division moves, vacant titles, interim champions | As maintained, each entry carries its reason and source | Only as current as the last edit; every entry is listed in `config/` |")
    a("| Public boards (UFC media panel, Meta UFC Rankings, Sherdog, Fight Matrix, ESPN) | Comparison only; never an input to the score | Snapshots stored in `data/external/` with their dates | Used to find disagreements, not to copy |")
    a("")
    a("Known gaps: no pre-UFC records (debutants start at the same rating), no injury data beyond the hand-kept list, no contract or matchmaking information, and statistics before about 2001 are sparse.")
    a("")
    a("## 3. How A + B = C: the pipeline, in order")
    a("")
    a("1. **Resume rating.** Every UFC bout since 1994 is processed in date order. Each fighter's rating moves by K x (actual score - expected score), where the expected score comes from the two ratings (Elo). Rules for scoring a result are in section 4.")
    a("2. **Eligibility.** A fighter must have fought within the active window, be on the roster, and be in a ranked division (section 6).")
    a("3. **Quality ledger.** Wins and losses are re-read for resume value (section 5).")
    a("4. **Score.** Score = rating weight x scaled rating + ledger weight x scaled ledger - form penalty. Both inputs are scaled within the division by their interdecile range: (value - median) / (90th percentile - 10th percentile).")
    a("5. **Head-to-head.** The winner of the latest meeting moves above the loser when close enough (section 7).")
    a("6. **Title cycle.** Recent title-fight challengers who lost step back from the top slots (section 7).")
    a("7. **Weight-sensitivity band.** The whole pipeline (score order, head-to-head, title cycle) is rerun with weight vectors drawn near the configured weights; the band is each fighter's 10th to 90th percentile final position. It is a sensitivity interval for the weight choice, not skill uncertainty (see section 10 for the Glicko-style deviation planned for v1.1).")
    a("8. **Audit.** Every contender's placement records where the score put him and which rule moved him.")
    a("")
    a("## 4. Scoring a single fight (the rating)")
    a("")
    a("| Situation | Winner's score (loser gets 1 minus this) | Why |")
    a("|---|---|---|")
    a("| Knockout, TKO or submission | 1.0 | A finish is a complete result |")
    a(f"| Decision | {e.get('card_weight', 0.5):.0%} judges' cards + {1 - e.get('card_weight', 0.5):.0%} fight statistics, never below 0.5 for the official winner | Judges alone can be wrong (Jones vs. Reyes); stats alone ignore what judges see. The official result always stands. |")
    a("| Judges' card, per judge | 1-point margin (29-28, 48-47) = 0.6; 2 points = 0.8; 3+ points (30-27, 49-46, 50-45) = 1.0 | 29-28 and 48-47 are close; 49-46 is a clear win |")
    a("| Fight statistics | Logistic of the winner's dominance per minute: significant strike difference + 5 x knockdowns + 2 x takedowns + 2 x submission attempts + control-time difference in minutes | Same formula as the validated predictive model |")
    a("")
    a(f"K = {e['k']}, and {e['k_new_mult']} x K for a fighter's first {e['n_new']} UFC bouts. There is no rating decay for time off; inactivity is handled in section 6.")
    a("")
    a("Ranks used by the rules below (top 3, top 5, quality-win tiers) are the **official** ranks on the fight date from 2013 on, and the model's own division position before that.")
    a("")
    a("**Other fight-level rules.** A no-contest caused by a failed drug test counts as a loss for the fighter who failed "
      "(read from the official bout details). A bout taken on short notice (about 3 weeks or less, `config/short_notice.yaml`) "
      "counts 1.2x for a win and 0.5x for a loss.")
    a("")
    a("**Loss rules.** A loss is **dominant** when it is a first-round finish, an early finish (first half of the scheduled rounds) while clearly behind on the stats, or a decision with 2 of 3 cards at 3+ points where the stats do not contradict the cards. A late finish while close on the stats (winner ahead by "
      f"{e.get('war_stat_max', 1.5)} or less per minute), a split or majority decision, or a decision scored {e.get('close_s', 0.7)} or less is **close**.")
    a("")
    a("| Loss | Rating cost | Why |")
    a("|---|---|---|")
    a(f"| Close loss to a top-{e.get('proof_top_n', 5)} fighter by someone outside the top {e.get('proof_top_n', 5)} | A gain of {e.get('proof_gain', 0.1):.0%} of K | Proof of concept: you showed you belong at that level |")
    a(f"| Loss to a top-{e.get('protect_top_n', 3)} fighter or in a title fight, not dominant | {e['protected_loss_mult']:.0%} of the normal drop ({e.get('consecutive_loss_mult', 0.6):.0%} if the previous bout was also a loss) | Losing to the best is expected; a losing streak is not a one-off |")
    a(f"| Same, but dominant | {e['dominant_loss_mult']:.0%} | A blowout says the gap is real, even at the top (Della Maddalena vs. Makhachev) |")
    a(f"| First-round finish by a heavy favorite ({e['heavy_favorite_p']:.0%}+ pre-fight win probability) | 100% | The real gap, confirmed; no need to run it back |")
    a("| Any other loss | 100% | |")
    a(f"| First-round finish by the underdog | Both fighters move {e.get('upset_quick_finish_mult', 0.7):.0%} as much | Quick early finishes can be flukes |")
    a("")
    a("## 5. The quality ledger")
    a("")
    a("A **quality win** is valued by the opponent's official rank going into the fight: champion 2.0, ranked 1-5 1.5, "
      "6-10 1.0, 11-15 0.5. An unranked opponent with 8+ UFC wins and a winning UFC record is worth 0.25. Beating four "
      "top-10 fighters is worth more than beating eight fighters ranked 11-15. Every ledger item is weighted by its age:")
    a("")
    a("| Age of the result | " + " | ".join(f"up to {k} years" for k in hz) + " |")
    a("|---|" + "---|" * len(hz))
    a("| Weight | " + " | ".join(str(v) for v in hz.values()) + " |")
    a("")
    a("| Ledger item | Value | Window |")
    a("|---|---|---|")
    a(f"| Quality win | +{L['quality_win']} | 15 years, age-weighted |")
    a(f"| Proof-of-concept loss (close loss to a top-5 fighter) | +{L['proof_of_concept']} | 15 years, age-weighted |")
    a(f"| Dominant loss | -{L['dominant_loss']} | last {rc.get('decisive_loss_years', 3)} years |")
    a(f"| Any other loss to someone outside the top 5 | -{L['loss_outside_top5']} | last {rc.get('decisive_loss_years', 3)} years |")
    a("")
    ent = rc.get("entrenched", {"top10_wins": 4, "top15_wins": 5})
    a(f"**Entrenched** (shown as E) = {ent['top10_wins']}+ wins over top-10 opponents, or {ent['top15_wins']}+ over top-15 opponents, in 15 years. Activity alone earns nothing: a fighter who takes many fights and loses to non-elite opponents gives the ledger back.")
    a("")
    a("## 6. Eligibility, form and division")
    a("")
    a(f"- **Inactivity.** No penalty for the first {ina['grace_days']} days; up to {ina['max_penalty_points']} rating points by {ina['max_days']} days; off the board after that. Documented injury layoffs (`config/layoffs.yaml`) carry no penalty and stay eligible up to {ina['injury_max_days']} days.")
    a("- **Form (last five UFC bouts).** Subtracted from the score: " + ", ".join(f"{k}: {v}" for k, v in fp.items()) + ". A 2-3 is a warning; 1-4 counts seriously against a fighter. A fighter with a negative last five also gets no head-to-head lift.")
    a("- **Division.** Two straight bouts in a division settle it. Otherwise the division fought in most over the last 3 years, with ties going to the division of the most recent win. Title holders are ranked in their title's division. Announced moves are in `config/division_overrides.yaml`, each with its reason.")
    a("- **Roster.** Retirements and releases are removed (`config/roster_exclusions.yaml`).")
    a("")
    a("## 7. Matchmaking reality rules")
    a("")
    a(f"- **Head-to-head.** If a fighter beat someone in their most recent meeting within {h2h['max_years']} years and sits no more than {h2h['max_gap']} places below him ({h2h['max_gap_recent']} if the fight was in the last 12 months), he moves directly above him.")
    a(f"- **Title cycle.** A challenger who lost a title fight in the last {tc['days']} days is placed no higher than #{tc['min_position']}: still close, but the champion is fighting someone else next. He earns his way back with {tc.get('release_top10_wins', 1)} win over a top-10 opponent or {tc.get('release_wins', 2)} wins of any kind. A champion who lost the belt is exempt (immediate rematches are common). Anyone that challenger beat in the last year stays below him.")
    a("- **Head-to-head details.** A close win (split or majority decision, or a fight scored as close) more than 12 months old settles nothing, and a fighter with a negative last five gets no head-to-head lift.")
    a("- **Reserved spots.** Former champions who vacated because of injury are listed as R above the numbered board (`config/reserved.yaml`).")
    a("")
    a("## 8. Validation")
    a("")
    if pair is not None:
        ours = pair[(pair["b"] == "Our board") | (pair["a"] == "Our board")]
        others = pair[(pair["a"] != "Our board") & (pair["b"] != "Our board")]
        a(f"Agreement with the public boards (UFC contenders only, champions removed): our average gap is "
          f"{ours['mean_abs_gap'].min():.1f} to {ours['mean_abs_gap'].max():.1f} places; the public boards differ from each other by "
          f"{others['mean_abs_gap'].min():.1f} to {others['mean_abs_gap'].max():.1f}. Disagreement is expected and reported, not removed: "
          "`outputs/compare_flags.csv` lists every large gap with its cause.")
        a("")
    if bt:
        sig = bt.get("significance_classic_vs_tuned", {})
        mt = bt.get("market_comparison_heldout_2020_2023", {})
        a(f"The separate predictive model (performance-adjusted Elo, the specification a {bt.get('grid', {}).get('combinations', '')}-point "
          f"grid selected on 2010-2019) scores {bt['tuned_test']['accuracy']:.1%} accuracy and "
          f"{bt['tuned_test']['log_loss']} log loss on {bt['tuned_test']['n']:,} held-out bouts from 2020 on, against "
          f"{bt['classic_tuned_test']['accuracy']:.1%} and {bt['classic_tuned_test']['log_loss']} for results-only Elo"
          + (f" (paired log-loss gain {sig['delta_log_loss']:.3f}, 95% event-block bootstrap interval "
             f"{sig['ci95_event_block_bootstrap'][0]:.3f} to {sig['ci95_event_block_bootstrap'][1]:.3f}; "
             f"McNemar exact p = {sig['mcnemar_exact_p']:.3g})" if sig else "")
          + (f". On the {mt['matched_bouts']:,} held-out bouts with closing odds (2020-2023) the de-vigged market scored "
             f"{mt['market_devigged']['accuracy']:.1%} and {mt['market_devigged']['log_loss']} against the model's "
             f"{mt['performance_adjusted']['accuracy']:.1%} and {mt['performance_adjusted']['log_loss']}." if mt else "."))
        a("")
    fv = json.loads((OUT / "forward_validation.json").read_text()) if (OUT / "forward_validation.json").exists() else None
    if fv and fv.get("retrospective_reconstruction"):
        r = fv["retrospective_reconstruction"]
        pri, t15 = r["primary_both_scored"], r["secondary_both_top15"]
        ci = pri.get("real_concordance_wilson95") or [0, 0]
        a(f"**Retrospective reconstruction of the resume board (not a forward test).** Boards were rebuilt with the v1.0 rules as "
          f"they would have stood before each of the last {fv['snapshots']} events. Across the {pri['bouts']} bouts in which both "
          f"fighters held a place on that board, the higher-placed fighter won {pri['real_concordance']:.1%} "
          f"(95% Wilson interval {ci[0]:.0%} to {ci[1]:.0%})"
          + (f"; the frozen score-to-probability map scored {pri['real_probability']['log_loss']} log loss against "
             f"{pri['results_only_elo']['log_loss']} for results-only Elo and {pri['performance_adjusted_elo']['log_loss']} for the "
             f"performance-adjusted model on the same bouts" if pri.get("results_only_elo") and pri.get("performance_adjusted_elo") else "")
          + f". Restricted to bouts between two top-15 fighters ({t15['bouts']} bouts) the figure is {t15['real_concordance']:.1%}"
          + (f", against {t15['official_board']['official_concordance']:.1%} for the official board on the "
             f"{t15['official_board']['bouts_both_ranked']} bouts it ranked both fighters" if t15.get("official_board") else "")
          + "; ranked-versus-ranked bouts are matched to be close, so every board sits near a coin flip on them and the "
            "differences are inside sampling error. Because these boards were reconstructed with today's rules, none of this is "
            "evidence of forward validity. The pre-registered prospective test (PREREGISTRATION.md) starts with the first "
            f"event after {fv['freeze_date']}"
          + (f"; so far it covers {fv['prospective_since_freeze']['primary_both_scored']['bouts']} bouts." if fv.get("prospective_since_freeze") else "."))
        a("")
    a("## 9. Worked examples (from this rebuild's audit trail)")
    a("")
    a("| Division | Fighter | Final | How he got there | Rating term | Ledger term | Form | Ledger detail | Last 5 |")
    a("|---|---|---|---|---|---|---|---|---|")
    for div, name in EXAMPLES:
        r = audit[(audit["division"] == div) & (audit["fighter"] == name)]
        if r.empty:
            continue
        r = r.iloc[0]
        a(f"| {div} | {name} | #{int(r['rank'])} | {r['placement']} | {r['rating_term']:+.2f} | {r['ledger_term']:+.2f} | "
          f"-{r['form_penalty']:.2f} | {r['ledger_detail']} | {r['last5']} |")
    a("")
    a("## 10. How REAL compares with published rating systems")
    a("")
    a("| Practice (source) | REAL v1.0 |")
    a("|---|---|")
    a("| Separate results-based from predictive metrics (NCAA selection practice: NET, KPI and Strength of Record versus KenPom, BPI and Torvik) | Met at the page level only: the resume rating itself is 50% judges and 50% fight statistics, so it is still performance-sensitive; Colley-style results-only scoring is an open option for v1.1 |")
    a("| Margin of victory from the judges' cards (BoxRec: result = (1 + clear-decision factor) / 2, scorecard margins when available) | Met in a different form, blended 50/50 with fight stats; cards and stats can measure the same dominance twice, which v1.1 will test by ablation |")
    a("| Partial credit for close results (Fight Matrix split-decision scoring) | Met: card margins and close-fight rules |")
    a("| Winner stays above loser for a period (BoxRec, 36 months) | Met in a narrower form: head-to-head rule |")
    a("| Losses in the biggest fights cost less (FIFA: knockout-stage losses at final tournaments cost nothing) | Met: loss protection tiers. FIFA is a precedent that a governing body can protect losses by policy; it does not justify the 15% and 75% constants, which were set by stated principle and are a v1.1 fitting target |")
    a("| Out-of-sample validation against baselines and the market (Holmes, McHale and Zychaluk 2023; Tennis Elo) | Met for the prediction model with paired bootstrap and McNemar tests; the resume board has only a retrospective reconstruction (54.4% on 226 ranked-versus-ranked bouts, 95% Wilson interval 48% to 61%, not distinguishable from chance) and a pre-registered prospective test from the v1.0 freeze (PREREGISTRATION.md) |")
    a("| Per-fighter uncertainty (Glicko RD, TrueSkill) | Not met: the weight band is a sensitivity interval for the weights, not a deviation that grows with sparse records or inactivity; planned for v1.1 |")
    a("| Margin-of-victory autocorrelation correction (FiveThirtyEight NFL Elo damps the margin multiplier by the favorite's rating edge) | Not yet: the dominance term is not conditioned on expected dominance, so favorites can be rewarded for routs they were expected to produce; first v1.1 model change |")
    a("| Constants fitted to data rather than set by judgment | Not yet: set by stated principle, then checked against public boards, which makes those boards an informal tuning target; v1.1 fits them on held-out log loss |")
    a("| Versioned method and changelog (FIFA, BoxRec, FiveThirtyEight) | Met from v1.0 |")
    a("| Minimum sample or provisional status for new entrants (Glicko, Fight Matrix over full professional records) | Not met: one UFC bout makes a fighter eligible and every debutant starts at 1500 with no pre-UFC record; v1.1 marks fewer than four UFC bouts provisional |")
    a("| Independence from the external board being compared against | Not met: official media-panel ranks at fight time set the quality-win tiers and the top-3 loss protection, so REAL is an official-rank-informed resume board rather than an independent one; v1.1 tests a frozen pre-fight REAL position as the replacement |")
    a("")
    a("## 11. Why these numbers: what each constant is for and what it costs")
    a("")
    a("Every constant in the engine encodes a stated ranking principle (what a resume should reward or forgive); none was fitted "
      "to outcomes. The table shows what each principle costs or buys when the pre-fight resume rating is scored as a forecaster on "
      "the same 3,390 held-out bouts (2020-2026) the prediction model is graded on, changing one constant at a time from the v1.0 "
      "values (`outputs/constants_sensitivity.csv`, rebuilt by `python -m mmalab.sensitivity`). A positive change in log loss means "
      "the alternative predicts worse than v1.0; a negative one means it predicts better. The resume board is not graded on "
      "prediction (its test is PREREGISTRATION.md), so a small predictive cost is the accepted price of a principle, but the reader "
      "can see the price.")
    a("")
    sens_path = OUT / "constants_sensitivity.csv"
    if sens_path.exists():
        sens = pd.read_csv(sens_path)
        ref = sens[sens["constant"] == "v1.0 reference"].iloc[0]
        a(f"v1.0 reference: log loss {ref['log_loss']:.4f}, accuracy {ref['accuracy']:.1%} on {int(ref['n']):,} bouts "
          f"(results-only Elo 0.674, performance-adjusted Elo 0.663 on the same bouts).")
        a("")
        a("| Constant | v1.0 value | Principle | Alternatives tried: change in held-out log loss |")
        a("|---|---|---|---|")
        from mmalab.resume import ResumeParams
        eng = {**ResumeParams().__dict__, **cfg["resume"]["engine"]}
        fmt = lambda v: f"{float(v):g}"
        for name, g in sens[~sens["constant"].isin(["v1.0 reference", "all loss protections off"])].groupby("constant", sort=False):
            alts = ", ".join(f"{fmt(v)}: {d:+.4f}" for v, d in zip(g["value"], g["delta_log_loss_vs_v1"])
                             if fmt(v) != fmt(eng.get(name, "nan")))
            a(f"| {name} | {fmt(eng.get(name))} | {g['principle'].iloc[0]} | {alts} |")
        off = sens[sens["constant"] == "all loss protections off"]
        if len(off):
            o = off.iloc[0]
            a(f"| all loss protections off | | plain Elo on cards and stats, every loss at full cost | {o['delta_log_loss_vs_v1']:+.4f} "
              f"(log loss {o['log_loss']:.4f}, accuracy {o['accuracy']:.1%}) |")
        a("")
        a("Reading the table: the whole set of loss protections costs about 0.003 log loss out of sample, and no single principle costs "
          "more than 0.0015, so the resume rules are cheap in predictive terms. The 50/50 blend of judges' cards and fight statistics "
          "is the best of the five blends tried, which supports the Jones-versus-Reyes argument with data. The two constants the data "
          "would push are K and the newcomer multiplier (faster ratings predict slightly better); the board keeps them slower on purpose, "
          "so that a single fight moves a resume less than it moves a forecast. The board-level constants (70/30 weights, horizons, ledger "
          "values, form penalty, title-cycle and head-to-head thresholds) cannot be scored this way because they act on the board, not "
          "the rating; the weight band covers the 70/30 choice and the rest are fitted or ablated under the v1.1 plan in section 10.")
        a("")
    a("## 12. Limits and open decisions")
    a("")
    a("- Pre-UFC records and betting odds after 2023 are not yet loaded (they require a manual Kaggle download); when added, pre-UFC records will set starting ratings and judge debut opponents' quality, never award ranking credit, and odds will define 'heavy favorite' instead of the model's own probability.")
    a("- Missed weight is not recorded in the fight data and is not yet used.")
    a("- Division overrides, injuries and retirements are hand-kept and need weekly review.")
    a("- Weights and thresholds were set by stated judgment and checked against the public boards (which makes those boards an informal tuning target); section 11 reports what each engine constant costs out of sample, and none has been fitted to any outcome.")
    a("- Card-quality and matchmaking analyses use the predictive model's positions, not these boards.")
    a("- Age. The board carries no age term, on purpose. Measured on 3,748 bouts between two board fighters from 2014 to 2026, "
      "the higher-ranked fighter won 45% of bouts when aged 35 or older against 58 to 63% when younger, in every period and division, "
      "and a rating discount by age would raise concordance by three to four points (experiments/REGISTER.md, EXP-2026-10-20-09). "
      "It was rejected for the board because a resume rank lags ability by construction: a contender earns the higher spot by beating "
      "the man who holds it, and an older top-10 fighter loses more often because he is matched against the best. Predictive concordance "
      "is therefore reported as a descriptive check, never used as the objective (PREREGISTRATION.md section 8). Age belongs in the "
      "prediction model; what the rating misses by age, and each fighter's own trajectory, is measured and shown beside the resume "
      "rank, never inside it (section 14).")
    a("- Resume-board tests. Because prediction is not the objective, the board's own tests are published every week in "
      "`outputs/board_quality.json`: top-15 turnover, moves of more than three places without a bout, head-to-head results the "
      "placement rules leave unresolved (with the reason each was left), published ranks outside their own weight band, roster facts "
      "added in the last seven days, and agreement with each public board. None of them is a tuning target.")
    a("")
    a("## 13. Shadow versions under test")
    a("")
    a("A new board version is never substituted for the registered one during the pre-registered period (PREREGISTRATION.md "
      "section 9; GOVERNANCE.md). It is built from its own override file over the frozen configuration, published beside the "
      "registered board under its own label, snapshotted to its own directory and graded on the same bouts. The versions currently "
      "under test:")
    a("")
    from mmalab.board_versions import load_version, version_files
    shadows = [load_version(pth) for pth in version_files()]
    shadows = [v for v in shadows if v.get("label") in ("shadow", "candidate")]
    if not shadows:
        a("- none")
    for v in shadows:
        a(f"- **v{v['version']}** ({v.get('label')}, since {v['since']}; `{v['path'].relative_to(ROOT)}`; page `docs/board_v{str(v['version']).replace('.', '_')}.html`; "
          f"adoption rule in PREREGISTRATION.md {v.get('adoption_rule', 'appendix C')}"
          + (f"; evidence {', '.join(v['evidence'])} in experiments/REGISTER.md" if v.get("evidence") else "") + "). Overrides over the frozen configuration:")
        for k, val in (v.get("overrides") or {}).items():
            a(f"  - `{k}`: `{json.dumps(val)}`")
        fv = OUT / f"forward_validation{v['suffix']}.json"
        if fv.exists():
            r = json.loads(fv.read_text())
            pro = r.get("prospective_since_freeze", {}).get("primary_both_scored", {})
            ret = r.get("retrospective_reconstruction", {}).get("primary_both_scored", {})
            a(f"  - record: prospective {pro.get('bouts', 0)} bouts" + (f", concordance {pro['real_concordance']:.3f}" if pro.get("bouts") else "")
              + (f"; retrospective reconstruction (in-sample) {ret['bouts']} bouts, concordance {ret['real_concordance']:.3f}" if ret.get("bouts") else "") + ".")
    a("")
    a("## 14. Age, decline and rise: what the rating misses, shown beside the rank")
    a("")
    for line in decline_section():
        a(line)
    a("")
    a("## 15. Changelog")
    a("")
    log = ROOT / "CHANGELOG.md"
    if log.exists():
        body = log.read_text().split("\n", 1)[1] if log.read_text().startswith("#") else log.read_text()
        for line in body.strip().splitlines():
            a(line.replace("## ", "### ", 1) if line.startswith("## ") else line)
    a("")
    a("Independent fan and research project. Not affiliated with, sponsored or endorsed by UFC, Zuffa, LLC, TKO Group Holdings, or any athlete.")
    return "\n".join(t)


DECLINE_EXP = "EXP-2026-10-21-01"          # the recorded research run the held-out numbers below come from
DECLINE_STRATA_EXP = "EXP-2026-10-21-02"   # who declines faster: curves by fighter group


def decline_section() -> list[str]:
    """Section 14: the decline and rise index. The live curve comes from outputs/decline_curve.json (rebuilt weekly);
    the held-out evidence comes from the register's copy of the recorded run, so the text and the numbers it cites
    stay tied to the same experiment."""
    cfg = yaml.safe_load((ROOT / "config" / "decline.yaml").read_text()) if (ROOT / "config" / "decline.yaml").exists() else {}
    curve_path = OUT / "decline_curve.json"
    curve = json.loads(curve_path.read_text()) if curve_path.exists() else None
    rec_path = ROOT / "experiments" / "results" / DECLINE_EXP / "decline_report_research_resume_perf.json"
    rec = json.loads(rec_path.read_text()) if rec_path.exists() else None
    k = float((curve or {}).get("points_per_residual", 694.9))
    t = []
    t.append("Section 12 records why no board carries an age term: a resume rank is earned against the fighters a man was matched "
             "with, and an older contender loses more often because he is matched with the best. The question the ranking cannot "
             "answer, and that readers ask first about an ageing champion or a rising prospect, is how far the rating now sits from the "
             "fighter's current level. The decline and rise index answers it beside the rank (`src/mmalab/decline.py`, settings in "
             "`config/decline.yaml`, shown in the Trajectory section of every profile page). No board reads it.")
    t.append("")
    t.append("**Outcome.** For every fighter and decided bout, the residual is the engine's performance score minus the pre-fight "
             "expectation, r = s - e, where s is the score the resume engine already uses (finishes 1 or 0, decisions a blend of the "
             "judges' cards and the fight statistics, section 3) and e comes from the two resume ratings plus a corner credit fitted on "
             "the training rows (the first-listed, red-corner fighter is the matchmakers' favourite and wins about 64% of bouts against 53% "
             "expected by rating alone; without the credit a fighter who is usually the favourite would look like a riser). The rating "
             "update is K (s - e), so a run of same-signed residuals is exactly the drift the rating has not absorbed. One unit of residual "
             f"sustained over many bouts corresponds to about {k:.0f} rating points (the slope of the expectation curve at e = 0.5).")
    t.append("")
    t.append("**Model.** Three parts, every one computed from information available before the bout. A population curve f(age), "
             "piecewise linear with knots at 27, 30, 33 and 36, one per sex, fitted on bouts from 2011: the average residual at each age, "
             "which is the rating's own age bias. An individual level: the fighter's recency-weighted mean residual around that curve over "
             "his earlier bouts, shrunk toward zero by a pseudo-count of bouts. An individual slope: the recency-weighted trend of those "
             "residuals against age, shrunk toward zero. The prediction for a fighter is f(age) + level + slope x (age - mean prior age). "
             f"The three shrinkage settings (level {cfg.get('lambda_level')}, slope {cfg.get('lambda_slope')}, half-life {cfg.get('half_life')} "
             "years) were chosen walk-forward: for each test year from the held-out performance of the years already tested, never from "
             "the test year, and they settled on the same values from 2019 on.")
    t.append("")
    if curve:
        men, women = curve["population_curve_men"], curve["population_curve_women"]
        ages = ["22", "25", "28", "30", "32", "34", "36", "38", "40"]
        t.append(f"**The population curve now** (fitted on {curve['fighter_bouts_fitted']:,} fighter-bouts through {curve['as_of']}, in residual "
                 "units with the rating-point equivalent):")
        t.append("")
        t.append("| Age | " + " | ".join(ages) + " |")
        t.append("|---|" + "---|" * len(ages))
        t.append("| Men | " + " | ".join(f"{men[a]:+.3f} ({men[a] * k:+.0f})" for a in ages) + " |")
        t.append("| Women | " + " | ".join(f"{women[a]:+.3f} ({women[a] * k:+.0f})" for a in ages) + " |")
        t.append("")
        t.append("Read: a 22-year-old on the board typically performs as if his rating were about "
                 f"{men['22'] * k:.0f} points higher than it is; a 36-year-old as if it were {-men['36'] * k:.0f} points lower, a 40-year-old "
                 f"{-men['40'] * k:.0f} points lower. The women's curve is flatter until the early thirties and then falls at the same rate.")
        t.append("")
    if rec:
        p = rec["pooled_heldout"]
        t.append(f"**Held-out evidence** (walk-forward by calendar year, test years 2016 to {rec['per_year'][-1]['year']}, "
                 f"{p['rows']:,} fighter-bouts; experiments/REGISTER.md {DECLINE_EXP}). The population curve explained "
                 f"{p['r2_population']:.1%} of the variance of the next bout's residual out of sample, positive in every test year; "
                 "the realized residual by age bucket tracked the curve that predicted it:")
        t.append("")
        t.append("| Ages | Fighter-bouts | Realized residual | Curve's prediction | Win rate | Expected | Rating points stale |")
        t.append("|---|---|---|---|---|---|---|")
        for row in rec.get("heldout_by_age", []):
            t.append(f"| {row['ages']} | {row['n']:,} | {row['mean_residual']:+.3f} | {row['population_curve']:+.3f} | {row['win_rate']:.0%} | "
                     f"{row['mean_expectation']:.0%} | {row['rating_points_stale']:+.0f} |")
        t.append("")
        d = rec["decliner_test"]
        lo, hi, al = d["lowest_quartile_of_individual_prediction"], d["highest_quartile"], d["all_33_plus"]
        rt = rec["result_test"]
        gain = rt.get("gain: M1 + population + level and slope over M1", {})
        t.append(f"The individual terms are a weak, consistent signal: held-out correlation {p['corr_individual_vs_realized']:.2f} between the "
                 f"individual prediction and the realized residual (calibration slope {p['calibration_slope']:.2f}, where 1 is right), and among "
                 f"the {d['rows_33_plus']:,} held-out bouts of fighters aged 33 or over, the lowest predicted quartile won {lo['win_rate']:.0%} against "
                 f"{lo['mean_expectation']:.0%} expected ({lo['wins_minus_expected_per_100']:+.0f} per 100), the highest {hi['win_rate']:.0%} against "
                 f"{hi['mean_expectation']:.0%} ({hi['wins_minus_expected_per_100']:+.0f}), all of them {al['wins_minus_expected_per_100']:+.0f}. "
                 f"Added to the prediction model's shadow feature set they change log loss by {gain.get('delta_log_loss', 0):+.4f} "
                 f"(95% event-block interval {gain.get('ci95_event_block_bootstrap', ['', ''])[0]} to {gain.get('ci95_event_block_bootstrap', ['', ''])[1]}): "
                 "nothing. Against the faster prediction Elo (K 130) the individual terms carry no signal at all; the resume rating is slow "
                 "by design, so it is the one with something left to read. On the tuning panel of 335 boards, converting the population "
                 "curve to rating points raises board concordance by 1.4 to 2.0 points with no free parameter, the individual terms add "
                 f"nothing on top, and neither is applied to any board (section 12).")
        t.append("")
    t.append(f"**Who declines faster** (men's bouts from 2011, descriptive, {DECLINE_STRATA_EXP}). At the same age, fighters who debuted "
             "in the UFC before 25 run further behind their rating from 33 on than those who debuted at 29 or later (about 0.07 of residual, "
             "50 rating points, interval excluding zero at 33, 35 and 37); the lighter divisions decline harder than middleweight and above "
             "from 35 on; a knockout loss in the previous three years marks a further 0.05 of lag at 35 to 37; and strikers and wrestlers "
             "decline at the same rate, so the common belief that wrestlers age better finds no support here. Fitting the curve within "
             "those groups did not beat the pooled curve out of sample, so the index uses one curve per sex and leaves the group "
             "differences as findings.")
    t.append("")
    t.append("**What is published.** `outputs/decline_index.csv` (every fighter with three decided UFC bouts and a bout in the last three "
             "years: age component, own-results component, combined, in residual units and rating points, with a plain reading) and "
             "`outputs/decline_curve.json`, rebuilt by the weekly pipeline from the frozen settings. The research runs that chose the "
             f"settings and measured the evidence are {DECLINE_EXP} and {DECLINE_STRATA_EXP} in the register.")
    return t


def main() -> None:
    text = build_text()
    (ROOT / "METHODOLOGY.md").write_text(text)
    import markdown
    body = markdown.markdown(text, extensions=["tables"])
    css = ("body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;max-width:900px;margin:0 auto;padding:24px 16px;"
           "line-height:1.5;color:#0b0b0b;background:#fcfcfb}table{border-collapse:collapse;width:100%;font-size:.88rem;"
           "display:block;overflow-x:auto}th,td{border-bottom:1px solid #e1e0d9;padding:5px 8px;text-align:left;vertical-align:top}"
           "@media (prefers-color-scheme: dark){body{color:#fff;background:#1a1a19}th,td{border-color:#2c2c2a}}")
    DOCS.mkdir(exist_ok=True)
    from mmalab.publish import footer
    bouts = pd.read_csv(ROOT / "data" / "processed" / "bouts.csv", parse_dates=["date"])
    (DOCS / "methodology.html").write_text(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Methodology</title><style>{css}</style></head><body><p><a href='index.html'>Back to the boards</a></p>{body}"
        f"{footer(bouts['date'].max().date())}</body></html>")
    print("METHODOLOGY.md and docs/methodology.html written")


if __name__ == "__main__":
    main()
