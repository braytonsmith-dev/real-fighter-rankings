# REAL Fighter Rankings: Methodology, version 1.0

*Results, Evidence, Analytics, Ledger.* Data through 2026-10-03. This document is generated from the live configuration (`config/weights.yaml`) and the audit trail (`outputs/audit_top30.csv`) on every rebuild.

## 1. What the rank means

A resume rank: who has earned the position as of today, updated automatically each week. The single principle behind every rule: **a fighter is ranked on how he performed against the fighters he faced, and how good those fighters were.** The goal is the most defensible board possible, not agreement with any other board. It is not a prediction of who would win tomorrow; that is a separate model (section 8, and the Prediction page). Champions (C), interim champions (IC) and reserved spots (R: former champions who vacated with an injury and are owed a title shot) sit above the numbered board with their metrics shown. Contenders are numbered 1 to 30.

## 2. Data and how far to trust it

| Source | What it provides | Coverage | Reliability |
|---|---|---|---|
| UFCStats (official UFC statistics), via the Greco1899 open scraper | Every UFC bout: result, method, round, time, judges' scorecards, round-by-round strikes, knockdowns, takedowns, submission attempts, control time | 8,925 bouts, 1994 to 2026-10-03; round stats for 99.8%; all three judges' cards for 98.6% of decisions (100% since 2005) | High for what it records. Strike counts are hand-coded and do not measure damage. Judges' cards are official but can be wrong. |
| Official UFC rankings history (martj42/ufc_rankings_history, every media-panel release Feb 2013 to June 2026, extended with weekly snapshots of ufc.com) | Each opponent's official rank on the day of the fight | 534 releases; about 99% of ranked names matched to UFCStats | High; before Feb 2013 the model's own position is used instead |
| Hand-kept configuration files | Retirements and releases, documented injury layoffs, announced division moves, vacant titles, interim champions | As maintained, each entry carries its reason and source | Only as current as the last edit; every entry is listed in `config/` |
| Public boards (UFC media panel, Meta UFC Rankings, Sherdog, Fight Matrix, ESPN) | Comparison only; never an input to the score | Snapshots stored in `data/external/` with their dates | Used to find disagreements, not to copy |

Known gaps: no pre-UFC records (debutants start at the same rating), no injury data beyond the hand-kept list, no contract or matchmaking information, and statistics before about 2001 are sparse.

## 3. How A + B = C: the pipeline, in order

1. **Resume rating.** Every UFC bout since 1994 is processed in date order. Each fighter's rating moves by K x (actual score - expected score), where the expected score comes from the two ratings (Elo). Rules for scoring a result are in section 4.
2. **Eligibility.** A fighter must have fought within the active window, be on the roster, and be in a ranked division (section 6).
3. **Quality ledger.** Wins and losses are re-read for resume value (section 5).
4. **Score.** Score = rating weight x scaled rating + ledger weight x scaled ledger - form penalty. Both inputs are scaled within the division by their interdecile range: (value - median) / (90th percentile - 10th percentile).
5. **Head-to-head.** The winner of the latest meeting moves above the loser when close enough (section 7).
6. **Title cycle.** Recent title-fight challengers who lost step back from the top slots (section 7).
7. **Weight-sensitivity band.** The whole pipeline (score order, head-to-head, title cycle) is rerun with weight vectors drawn near the configured weights; the band is each fighter's 10th to 90th percentile final position. It is a sensitivity interval for the weight choice, not skill uncertainty (see section 10 for the Glicko-style deviation planned for v1.1).
8. **Audit.** Every contender's placement records where the score put him and which rule moved him.

## 4. Scoring a single fight (the rating)

| Situation | Winner's score (loser gets 1 minus this) | Why |
|---|---|---|
| Knockout, TKO or submission | 1.0 | A finish is a complete result |
| Decision | 50% judges' cards + 50% fight statistics, never below 0.5 for the official winner | Judges alone can be wrong (Jones vs. Reyes); stats alone ignore what judges see. The official result always stands. |
| Judges' card, per judge | 1-point margin (29-28, 48-47) = 0.6; 2 points = 0.8; 3+ points (30-27, 49-46, 50-45) = 1.0 | 29-28 and 48-47 are close; 49-46 is a clear win |
| Fight statistics | Logistic of the winner's dominance per minute: significant strike difference + 5 x knockdowns + 2 x takedowns + 2 x submission attempts + control-time difference in minutes | Same formula as the validated predictive model |

K = 60, and 1.5 x K for a fighter's first 5 UFC bouts. There is no rating decay for time off; inactivity is handled in section 6.

Ranks used by the rules below (top 3, top 5, quality-win tiers) are the **official** ranks on the fight date from 2013 on, and the model's own division position before that.

**Other fight-level rules.** A no-contest caused by a failed drug test counts as a loss for the fighter who failed (read from the official bout details). A bout taken on short notice (about 3 weeks or less, `config/short_notice.yaml`) counts 1.2x for a win and 0.5x for a loss.

**Loss rules.** A loss is **dominant** when it is a first-round finish, an early finish (first half of the scheduled rounds) while clearly behind on the stats, or a decision with 2 of 3 cards at 3+ points where the stats do not contradict the cards. A late finish while close on the stats (winner ahead by 1.5 or less per minute), a split or majority decision, or a decision scored 0.7 or less is **close**.

| Loss | Rating cost | Why |
|---|---|---|
| Close loss to a top-5 fighter by someone outside the top 5 | A gain of 10% of K | Proof of concept: you showed you belong at that level |
| Loss to a top-3 fighter or in a title fight, not dominant | 15% of the normal drop (60% if the previous bout was also a loss) | Losing to the best is expected; a losing streak is not a one-off |
| Same, but dominant | 75% | A blowout says the gap is real, even at the top (Della Maddalena vs. Makhachev) |
| First-round finish by a heavy favorite (75%+ pre-fight win probability) | 100% | The real gap, confirmed; no need to run it back |
| Any other loss | 100% | |
| First-round finish by the underdog | Both fighters move 70% as much | Quick early finishes can be flukes |

## 5. The quality ledger

A **quality win** is valued by the opponent's official rank going into the fight: champion 2.0, ranked 1-5 1.5, 6-10 1.0, 11-15 0.5. An unranked opponent with 8+ UFC wins and a winning UFC record is worth 0.25. Beating four top-10 fighters is worth more than beating eight fighters ranked 11-15. Every ledger item is weighted by its age:

| Age of the result | up to 3 years | up to 5 years | up to 10 years | up to 15 years |
|---|---|---|---|---|
| Weight | 1.0 | 0.6 | 0.3 | 0.1 |

| Ledger item | Value | Window |
|---|---|---|
| Quality win | +1.0 | 15 years, age-weighted |
| Proof-of-concept loss (close loss to a top-5 fighter) | +0.5 | 15 years, age-weighted |
| Dominant loss | -1.0 | last 3 years |
| Any other loss to someone outside the top 5 | -1.0 | last 3 years |

**Entrenched** (shown as E) = 4+ wins over top-10 opponents, or 5+ over top-15 opponents, in 15 years. Activity alone earns nothing: a fighter who takes many fights and loses to non-elite opponents gives the ledger back.

## 6. Eligibility, form and division

- **Inactivity.** No penalty for the first 365 days; up to 50 rating points by 540 days; off the board after that. Documented injury layoffs (`config/layoffs.yaml`) carry no penalty and stay eligible up to 730 days.
- **Form (last five UFC bouts).** Subtracted from the score: 2-3: 0.15, 1-4: 0.6, 0-5: 0.8. A 2-3 is a warning; 1-4 counts seriously against a fighter. A fighter with a negative last five also gets no head-to-head lift.
- **Division.** Two straight bouts in a division settle it. Otherwise the division fought in most over the last 3 years, with ties going to the division of the most recent win. Title holders are ranked in their title's division. Announced moves are in `config/division_overrides.yaml`, each with its reason.
- **Roster.** Retirements and releases are removed (`config/roster_exclusions.yaml`).

## 7. Matchmaking reality rules

- **Head-to-head.** If a fighter beat someone in their most recent meeting within 3 years and sits no more than 3 places below him (6 if the fight was in the last 12 months), he moves directly above him.
- **Title cycle.** A challenger who lost a title fight in the last 270 days is placed no higher than #4: still close, but the champion is fighting someone else next. He earns his way back with 1 win over a top-10 opponent or 2 wins of any kind. A champion who lost the belt is exempt (immediate rematches are common). Anyone that challenger beat in the last year stays below him.
- **Head-to-head details.** A close win (split or majority decision, or a fight scored as close) more than 12 months old settles nothing, and a fighter with a negative last five gets no head-to-head lift.
- **Reserved spots.** Former champions who vacated because of injury are listed as R above the numbered board (`config/reserved.yaml`).

## 8. Validation

Agreement with the public boards (UFC contenders only, champions removed): our average gap is 1.7 to 2.0 places; the public boards differ from each other by 0.9 to 1.6. Disagreement is expected and reported, not removed: `outputs/compare_flags.csv` lists every large gap with its cause.

The separate predictive model (performance-adjusted Elo, the specification a 520-point grid selected on 2010-2019) scores 60.6% accuracy and 0.6631 log loss on 3,390 held-out bouts from 2020 on, against 58.1% and 0.674 for results-only Elo (paired log-loss gain 0.011, 95% event-block bootstrap interval 0.006 to 0.016; McNemar exact p = 0.0025). On the 1,445 held-out bouts with closing odds (2020-2023) the de-vigged market scored 67.1% and 0.6088 against the model's 60.0% and 0.669.

**Retrospective reconstruction of the resume board (not a forward test).** Boards were rebuilt with the v1.0 rules as they would have stood before each of the last 128 events. Across the 942 bouts in which both fighters held a place on that board, the higher-placed fighter won 61.5% (95% Wilson interval 58% to 64%); the frozen score-to-probability map scored 0.6669 log loss against 0.6726 for results-only Elo and 0.6498 for the performance-adjusted model on the same bouts. Restricted to bouts between two top-15 fighters (226 bouts) the figure is 54.4%, against 52.0% for the official board on the 204 bouts it ranked both fighters; ranked-versus-ranked bouts are matched to be close, so every board sits near a coin flip on them and the differences are inside sampling error. Because these boards were reconstructed with today's rules, none of this is evidence of forward validity. The pre-registered prospective test (PREREGISTRATION.md) starts with the first event after 2026-10-01; so far it covers 8 bouts.

## 9. Worked examples (from this rebuild's audit trail)

| Division | Fighter | Final | How he got there | Rating term | Ledger term | Form | Ledger detail | Last 5 |
|---|---|---|---|---|---|---|---|---|
| Bantamweight | Mario Bautista | #5 | score order #5 | +0.47 | +0.23 | -0.00 | +3.6 QW +0.0 proof -1.0 blowout -0.0 weak | 4-1 |
| Bantamweight | Cory Sandhagen | #6 | score order #6 | +0.64 | +0.21 | -0.15 | +5.3 QW +0.0 proof -2.0 blowout -1.0 weak | 2-3 |
| Light Heavyweight | Jiri Prochazka | #4 | score order #2; title cycle -> #4 | +0.54 | +0.29 | -0.00 | +6.5 QW +0.0 proof -2.0 blowout -0.0 weak | 3-2 |
| Light Heavyweight | Khalil Rountree Jr. | #9 | score order #9 | +0.22 | +0.22 | -0.00 | +3.1 QW +0.0 proof -0.0 blowout -0.0 weak | 3-2 |
| Heavyweight | Alex Pereira | #4 | score order #1; title cycle -> #4 | +0.74 | +0.46 | -0.00 | +10.5 QW +0.0 proof -1.0 blowout -0.0 weak | 3-2 |
| Welterweight | Kamaru Usman | #10 | score order #10 | +0.76 | +0.29 | -0.60 | +5.2 QW +0.0 proof -1.0 blowout -0.0 weak | 1-4 |
| Welterweight | Kevin Holland | #24 | score order #24 | +0.31 | -0.12 | -0.00 | +1.8 QW +0.0 proof -2.0 blowout -3.0 weak | 3-2 |
| Flyweight | Brandon Moreno | #6 | score order #4; title cycle -> #6 | +0.36 | +0.28 | -0.00 | +6.6 QW +0.0 proof -0.0 blowout -1.0 weak | 3-2 |
| Lightweight | Max Holloway | #2 | score order #1; head-to-head -> #2 | +0.93 | +0.63 | -0.00 | +8.4 QW +0.0 proof -1.0 blowout -0.0 weak | 3-2 |

## 10. How REAL compares with published rating systems

| Practice (source) | REAL v1.0 |
|---|---|
| Separate results-based from predictive metrics (NCAA selection practice: NET, KPI and Strength of Record versus KenPom, BPI and Torvik) | Met at the page level only: the resume rating itself is 50% judges and 50% fight statistics, so it is still performance-sensitive; Colley-style results-only scoring is an open option for v1.1 |
| Margin of victory from the judges' cards (BoxRec: result = (1 + clear-decision factor) / 2, scorecard margins when available) | Met in a different form, blended 50/50 with fight stats; cards and stats can measure the same dominance twice, which v1.1 will test by ablation |
| Partial credit for close results (Fight Matrix split-decision scoring) | Met: card margins and close-fight rules |
| Winner stays above loser for a period (BoxRec, 36 months) | Met in a narrower form: head-to-head rule |
| Losses in the biggest fights cost less (FIFA: knockout-stage losses at final tournaments cost nothing) | Met: loss protection tiers. FIFA is a precedent that a governing body can protect losses by policy; it does not justify the 15% and 75% constants, which were set by stated principle and are a v1.1 fitting target |
| Out-of-sample validation against baselines and the market (Holmes, McHale and Zychaluk 2023; Tennis Elo) | Met for the prediction model with paired bootstrap and McNemar tests; the resume board has only a retrospective reconstruction (54.4% on 226 ranked-versus-ranked bouts, 95% Wilson interval 48% to 61%, not distinguishable from chance) and a pre-registered prospective test from the v1.0 freeze (PREREGISTRATION.md) |
| Per-fighter uncertainty (Glicko RD, TrueSkill) | Not met: the weight band is a sensitivity interval for the weights, not a deviation that grows with sparse records or inactivity; planned for v1.1 |
| Margin-of-victory autocorrelation correction (FiveThirtyEight NFL Elo damps the margin multiplier by the favorite's rating edge) | Not yet: the dominance term is not conditioned on expected dominance, so favorites can be rewarded for routs they were expected to produce; first v1.1 model change |
| Constants fitted to data rather than set by judgment | Not yet: set by stated principle, then checked against public boards, which makes those boards an informal tuning target; v1.1 fits them on held-out log loss |
| Versioned method and changelog (FIFA, BoxRec, FiveThirtyEight) | Met from v1.0 |
| Minimum sample or provisional status for new entrants (Glicko, Fight Matrix over full professional records) | Not met: one UFC bout makes a fighter eligible and every debutant starts at 1500 with no pre-UFC record; v1.1 marks fewer than four UFC bouts provisional |
| Independence from the external board being compared against | Not met: official media-panel ranks at fight time set the quality-win tiers and the top-3 loss protection, so REAL is an official-rank-informed resume board rather than an independent one; v1.1 tests a frozen pre-fight REAL position as the replacement |

## 11. Why these numbers: what each constant is for and what it costs

Every constant in the engine encodes a stated ranking principle (what a resume should reward or forgive); none was fitted to outcomes. The table shows what each principle costs or buys when the pre-fight resume rating is scored as a forecaster on the same 3,390 held-out bouts (2020-2026) the prediction model is graded on, changing one constant at a time from the v1.0 values (`outputs/constants_sensitivity.csv`, rebuilt by `python -m mmalab.sensitivity`). A positive change in log loss means the alternative predicts worse than v1.0; a negative one means it predicts better. The resume board is not graded on prediction (its test is PREREGISTRATION.md), so a small predictive cost is the accepted price of a principle, but the reader can see the price.

v1.0 reference: log loss 0.6757, accuracy 57.9% on 3,390 bouts (results-only Elo 0.674, performance-adjusted Elo 0.663 on the same bouts).

| Constant | v1.0 value | Principle | Alternatives tried: change in held-out log loss |
|---|---|---|---|
| k | 60 | rating speed; 60 sits between chess (20 to 40) and Fight Matrix (170) | 30: +0.0054, 45: +0.0021, 80: -0.0015, 100: -0.0014 |
| k_new_mult | 1.5 | newcomers converge faster (FIDE practice), first n_new = 5 bouts | 1: +0.0040, 2: -0.0021 |
| protected_loss_mult | 0.15 | a non-dominant loss in a title fight or to a top-3 fighter counts for little | 0: +0.0002, 0.3: -0.0003, 0.5: -0.0006, 1: -0.0013 |
| dominant_loss_mult | 0.75 | a dominant loss in that context still costs most of its value | 0.5: +0.0006, 1: -0.0006 |
| consecutive_loss_mult | 0.6 | protection weakens on a second straight loss | 0.15: +0.0001, 1: -0.0001 |
| heavy_favorite_p | 0.75 | a round-one finish by a favorite at or above this probability costs full value (1.01 = never) | 0.6: +0.0000, 0.9: +0.0000, 1.01: +0.0000 |
| card_weight | 0.5 | decisions: share of the result taken from the judges' cards, the rest from fight statistics | 0: +0.0008, 0.25: +0.0002, 0.75: +0.0001, 1: +0.0005 |
| stat_scale | 2 | dominance per minute that maps to about 73% of a performance win | 1: -0.0009, 3: +0.0008 |
| close_s | 0.7 | a decision at or below this blended score counts as close (29-28 territory) | 0.6: +0.0000, 0.8: +0.0002 |
| proof_gain | 0.1 | close loss to a top-5 fighter by someone outside the top 5 gains this share of K | 0: -0.0002, 0.2: +0.0002 |
| proof_top_n | 5 | the rank that defines an elite opponent for proof of concept | 3: -0.0002, 7: +0.0000 |
| protect_top_n | 3 | the rank at or above which an opponent's win is a protected context | 1: -0.0004, 5: +0.0008 |
| upset_quick_finish_mult | 0.7 | a round-one upset finish moves both fighters by this share | 0.5: +0.0014, 1: -0.0015 |
| all loss protections off | | plain Elo on cards and stats, every loss at full cost | -0.0033 (log loss 0.6724, accuracy 58.2%) |

Reading the table: the whole set of loss protections costs about 0.003 log loss out of sample, and no single principle costs more than 0.0015, so the resume rules are cheap in predictive terms. The 50/50 blend of judges' cards and fight statistics is the best of the five blends tried, which supports the Jones-versus-Reyes argument with data. The two constants the data would push are K and the newcomer multiplier (faster ratings predict slightly better); the board keeps them slower on purpose, so that a single fight moves a resume less than it moves a forecast. The board-level constants (70/30 weights, horizons, ledger values, form penalty, title-cycle and head-to-head thresholds) cannot be scored this way because they act on the board, not the rating; the weight band covers the 70/30 choice and the rest are fitted or ablated under the v1.1 plan in section 10.

## 12. Limits and open decisions

- Pre-UFC records and betting odds after 2023 are not yet loaded (they require a manual Kaggle download); when added, pre-UFC records will set starting ratings and judge debut opponents' quality, never award ranking credit, and odds will define 'heavy favorite' instead of the model's own probability.
- Missed weight is not recorded in the fight data and is not yet used.
- Division overrides, injuries and retirements are hand-kept and need weekly review.
- Weights and thresholds were set by stated judgment and checked against the public boards (which makes those boards an informal tuning target); section 11 reports what each engine constant costs out of sample, and none has been fitted to any outcome.
- Card-quality and matchmaking analyses use the predictive model's positions, not these boards.

## 13. Changelog

- **1.0 (Oct 1, 2026).** Method frozen for forward grading. Official rank at fight time (2013+); tiered quality wins; proof-of-concept credit for close losses to top-5 fighters; early-finish and war rules; drug-test overturns count as losses; short-notice credit; last-five form penalty; division, head-to-head, title-cycle and reserved-spot rules; audit trail; prediction model published separately.
- **1.0.1 (Oct 1, 2026, display and documentation only; no ranking rule changed).** Weight band recomputed after the head-to-head and title-cycle rules so every published rank lies inside its own band; prediction page and card-quality positions switched to the specification the grid selected on 2010-2019 (one model in the paper); paired bootstrap and McNemar tests, the market on the held-out overlap, the constants sensitivity table (section 11), PREREGISTRATION.md and DATA_LICENSE.md added; favorites page moved out of the research navigation.
- **0.x (Sept 29-30, 2026).** Composite of six percentile dimensions, replaced after review because four dimensions carried no ranking signal and losses were counted three times.

Independent fan and research project. Not affiliated with, sponsored or endorsed by UFC, Zuffa, LLC, TKO Group Holdings, or any athlete.