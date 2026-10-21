# Experiment register

Every test, pilot and candidate comparison run on REAL, in order. Rendered from `experiments/register.jsonl` by `python -m mmalab.experiments`; edit the JSONL (or call `mmalab.experiments.record`), not this file. The protocol and the entry template are in `experiments/README.md`.

| ID | Date | Title | Decision |
|---|---|---|---|
| [EXP-2026-09-30-01](#exp-2026-09-30-01) | 2026-09-30 | Composite board replaced by the resume board | adopted |
| [EXP-2026-10-01-01](#exp-2026-10-01-01) | 2026-10-01 | Predictive Elo grid search and significance (the SSAC abstract result) | adopted |
| [EXP-2026-10-01-02](#exp-2026-10-01-02) | 2026-10-01 | Board score to probability: the frozen slope 1.36 | adopted |
| [EXP-2026-10-05-01](#exp-2026-10-05-01) | 2026-10-05 | Shadow prediction model v1.1 (walk-forward Elo re-tune plus logistic layer) | parked |
| [EXP-2026-10-20-01](#exp-2026-10-20-01) | 2026-10-20 | Loss-handling candidates on 43 full boards (finding 1) | adopted |
| [EXP-2026-10-20-02](#exp-2026-10-20-02) | 2026-10-20 | Protected-loss multiplier and Kamaru Usman | informational |
| [EXP-2026-10-20-03](#exp-2026-10-20-03) | 2026-10-20 | Panel comparison: v1.0 rules vs B+0 under two engines | informational |
| [EXP-2026-10-20-04](#exp-2026-10-20-04) | 2026-10-20 | Walk-forward tuning of the board rules, first pass (search blind spot) | superseded |
| [EXP-2026-10-20-05](#exp-2026-10-20-05) | 2026-10-20 | Hindsight re-grading of results (curator's idea) | parked |
| [EXP-2026-10-20-06](#exp-2026-10-20-06) | 2026-10-20 | Walk-forward tuning, second pass: coupled coordinates, free and resume presets | informational |
| [EXP-2026-10-20-07](#exp-2026-10-20-07) | 2026-10-20 | Rating-engine sweep (K, protection, consecutive-loss rule, protection ladder, no official ranks) | informational |
| [EXP-2026-10-20-08](#exp-2026-10-20-08) | 2026-10-20 | v1.1 retrospective reconstruction (its own snapshot directory) | informational |
| [EXP-2026-10-20-09](#exp-2026-10-20-09) | 2026-10-20 | Age and the rating channel: older favourites lose more often than they win | rejected |
| [EXP-2026-10-20-10](#exp-2026-10-20-10) | 2026-10-20 | Glicko-1 rating deviation for the resume rating: parameter derivation and calibration | adopted |
| [EXP-2026-10-20-11](#exp-2026-10-20-11) | 2026-10-20 | Placement layer as one constrained order (solver) versus the sequential head-to-head and title-cycle loops | adopted |
| [EXP-2026-10-20-12](#exp-2026-10-20-12) | 2026-10-20 | v1.1 as shipped (loss tiers, form, protection 0.30, placement solver) on 43 full boards, corrected data | adopted |
| [EXP-2026-10-20-13](#exp-2026-10-20-13) | 2026-10-20 | Literature sweep: aging, damage accumulation, style and longevity, time-varying rating models, finding the outlier | informational |
| [EXP-2026-10-20-14](#exp-2026-10-20-14) | 2026-10-20 | Fighter profiles: do career statistics add to age in predicting bouts? | rejected |
| [EXP-2026-10-20-15](#exp-2026-10-20-15) | 2026-10-20 | v1.2 candidate from the resume-preset walk-forward: face validity on today's board | rejected |
| [EXP-2026-10-21-01](#exp-2026-10-21-01) | 2026-10-21 | Decline and rise index: the population age curve of the rating residual plus a shrunken per-fighter level and slope | adopted |
| [EXP-2026-10-21-02](#exp-2026-10-21-02) | 2026-10-21 | Who declines faster: the population curve by style, debut age, weight band, UFC tenure and recent knockout loss | informational |

## EXP-2026-09-30-01

Composite board replaced by the resume board  
Date 2026-09-30, decision: adopted, code at commit `see CHANGELOG 1.0`.

Question. Does a six-dimension percentile composite (rating 45%, form 10%, entrenchment 20%, offense 10%, activity 5%, durability 10%) rank fighters better than a resume score (rating 70% + quality ledger 30% - form penalty)?

| Method | |
|---|---|
| instrument | retrospective reconstruction and review of the published boards |
| window | Sept 2026 boards |
| metric | concordance with later results; review of which dimensions carried ranking signal |
| baseline | the composite |

Candidate. Resume board (Option B): REAL rating 70%, quality ledger 30%, last-five form penalty, head-to-head and title-cycle placement rules

| Result | |
|---|---|
| finding | four of the six composite dimensions carried no ranking signal and losses were counted three times (rating, form, durability) |
| outcome | resume board adopted as v1.0 and frozen Oct 1, 2026 (CHANGELOG.md 0.x and 1.0) |

Decision. adopted: The composite's extra dimensions added noise, not information; the resume score is interpretable and no less accurate.

## EXP-2026-10-01-01

Predictive Elo grid search and significance (the SSAC abstract result)  
Date 2026-10-01, decision: adopted, code at commit `d4a9325`.

Question. Which Elo specification predicts UFC bouts best out of sample, and is the performance-adjusted model better than results-only Elo?

| Method | |
|---|---|
| instrument | src/mmalab/backtest.py grid of 520 combinations |
| warmup | 1994-2009 |
| tune | 2010-2019 (selection by log loss) |
| test | 2020-2026, 3,390 bouts, 287 events |
| baseline | results-only Elo tuned the same way (classic_tuned_params) |
| interval | paired event-block bootstrap 5,000 draws; exact McNemar on discordant bouts |

Candidate. `{"tuned_params": {"k": 130, "k_new_mult": 1.5, "n_new": 5, "split_mult": 0.8, "layoff_regress_per_year": 0.25, "mov_weight": 0.9, "mov_scale": 2.0, "win_floor": 0.5, "finish_floor": 0.0}}`

| Result | |
|---|---|
| tuned (held out 2020-2026) | log loss 0.6631, accuracy 60.6% |
| results-only | log loss 0.6740, accuracy 58.1% |
| gain | 0.0109 log loss, CI 0.0057 to 0.0162; McNemar p = 0.0025 (429 vs 344 discordant bouts) |
| market (1,445 held-out bouts with closing odds, 2020-2023) | market 0.6088 / 67.1%; model 0.669 / 60.0%; 50/50 blend 0.6292 / 66.2% |
| calibration in the large | mean predicted first-listed 0.535 vs observed 0.572 (no corner term in v1.0) |

Decision. adopted: The pre-registered headline for the SSAC27 abstract; the interpretable site specification (0.6621 / 61.2%) is reported as a second specification only.

Files: `experiments/results/EXP-2026-10-01-01/backtest_report.json`

## EXP-2026-10-01-02

Board score to probability: the frozen slope 1.36  
Date 2026-10-01, decision: adopted, code at commit `d4a9325`.

Question. What logistic slope maps a REAL score difference to a win probability, for the pre-registered forward test?

| Method | |
|---|---|
| instrument | src/mmalab/history.py retrospective reconstruction |
| window | 127 reconstructed boards, Oct 2023 to Sept 2026 |
| bouts | 942 |
| metric | log loss, one-parameter symmetric logistic |
| baseline | none (calibration step) |

Candidate. p = 1 / (1 + exp(-1.36 x (score_a - score_b)))

| Result | |
|---|---|
| retrospective log loss | 0.667 |
| concordance of the published order | 61.5% (in-sample reconstruction) |

Decision. adopted: Frozen in PREREGISTRATION.md section 5; scored prospectively from Oct 2, 2026.

## EXP-2026-10-05-01

Shadow prediction model v1.1 (walk-forward Elo re-tune plus logistic layer)  
Date 2026-10-05, decision: parked, code at commit `d4a9325`.

Question. Does re-tuning the Elo parameters walk-forward over 2011 onward, with a red-corner term and a logistic layer (age, layoff, experience, height, five rounds), beat the frozen v1.0 predictive model?

| Method | |
|---|---|
| instrument | src/mmalab/shadow.py coordinate descent, parameters chosen on 2011..Y-1 and scored on Y |
| window | 2016-2026 (5,308 bouts), out of sample for both models 2020-2026 (3,404 bouts, 288 events) |
| metric | log loss, Brier, accuracy |
| baseline | v1.0 frozen predictive model on the same bouts |
| interval | paired event-block bootstrap |

Candidate. `{"final_shadow_params": {"k": 130, "split_mult": 0.6, "layoff_regress_per_year": 0.4, "mov_weight": 0.9, "win_floor": 0.0, "finish_floor": 0.6, "corner_adv": 35, "mov_damp": 0.0}, "logistic features": ["elo_diff", "age_diff", "old_diff", "layoff_diff", "debut_diff", "exp_diff", "height_diff", "five_round", "elo_x_five"]}`

| Result | |
|---|---|
| 2020-2026 | v1.1 Elo+logistic 0.6398 / 63.1% vs v1.0 0.6632 / 60.6%; gain 0.0234, CI 0.0167 to 0.0300 |
| market, 3,022 bouts 2016-2023 | market 0.6118 / 66.0%; v1.1 0.6558 / 61.9%; v1.0 0.6683 / 59.7% |
| calibration in the large | v1.1 mean 0.584 vs observed 0.572 (within 3 points) |

Decision. parked: Published only as a shadow in the picks ledger; adopted under PREREGISTRATION.md appendix B after 300 graded paired picks with a log-loss gain whose interval excludes zero.

Files: `experiments/results/EXP-2026-10-05-01/shadow_v11_report.json`

## EXP-2026-10-20-01

Loss-handling candidates on 43 full boards (finding 1)  
Date 2026-10-20, decision: adopted, code at commit `d4a9325`.

Question. Does softening and making opponent-aware the three channels that charge a loss (ledger cost, form penalty, rating protection) cost accuracy?

| Method | |
|---|---|
| instrument | resume_board.build at every third event date, every placement rule applied (head-to-head, title cycle), published order |
| window | Oct 2023 to Oct 17, 2026, 43 event-eve boards |
| bouts | 947 decided bouts between two fighters on the same divisional board |
| metric | concordance of the published order with the winner; log loss with the frozen v1.0 slope 1.36 |
| baseline | v1.0 rules on the same bouts |
| interval | paired event-block bootstrap (all candidates' intervals against v1.0 straddle zero) |

Candidate. `{"v1.0": "frozen rules", "B+ (Bplus)": "ledger loss tiers [[5,0.25],[10,0.5],[15,0.75],[999,1.0]], dominant_extra 0.25; form buckets 2-3 0.10 / 1-4 0.30 / 0-5 0.40; bad-loss add-on 0.10 per last-five loss outside the top 10, cap 0.30", "B+0 (Bplus0)": "as B+ with dominant_extra 0.0", "v1.1": "B+0 plus engine protected_loss_mult 0.30", "R": "rating only (no ledger, no form penalty)", "B, C, F": "intermediate rule sets whose exact definitions were lost with the session context on Oct 20; results kept for the record"}`

| Result | |
|---|---|
| v1.0 | all 0.6077 / 0.6706; top 30 0.5667; top 15 0.5349 / 0.7122 |
| v1.1 (B+0, protection 0.30) | all 0.6056 / 0.6659; top 30 0.5632; top 15 0.5360 / 0.7056 |
| B+ | all 0.6067 / 0.6655; top 30 0.5625; top 15 0.5511 / 0.7012 |
| B+0 | all 0.6045 / 0.6664; top 30 0.5611; top 15 0.5298 / 0.7062 |
| B | all 0.6077 / 0.6659; top 30 0.5583; top 15 0.5472 / 0.7031 |
| C | all 0.6003 / 0.6705; top 30 0.5513; top 15 0.5249 / 0.7069 |
| F | all 0.6024 / 0.6716; top 30 0.5503; top 15 0.5290 / 0.7091 |
| R (rating only) | all 0.5876 / 0.6729; top 30 0.5589; top 15 0.5440 / 0.6949 |
| paired intervals | every candidate's 95% interval against v1.0 straddles zero on 947 bouts; rating-only is about 2 points worse, so the ledger and form carry information |

| Face validity | |
|---|---|
| Buckley (WW) | 21 to 15 |
| Adesanya (MW) | 27 to 14 |
| Blachowicz (LHW) | 27 to 13 |
| Vera (BW) | 54 to 14 |
| Ortega (FW) | 40 to 15 |
| Usman (WW) | 9 to 5 (curator: 7 is closer) |
| largest unintended moves | Jim Miller 11 to 19, Jalin Turner 15 to 23, Neil Magny 15 to 22 |

Decision. adopted: v1.1 = B+0 with protection 0.30 adopted as a shadow board on face validity at equal measured accuracy (CHANGELOG 1.1). The 43-board instrument cannot separate the candidates (audit V1), which is why the 2014-2026 panel was built next.

Files: `experiments/results/EXP-2026-10-20-01/eval_v10.json`, `experiments/results/EXP-2026-10-20-01/eval_v11.json`, `experiments/results/EXP-2026-10-20-01/eval_B.json`, `experiments/results/EXP-2026-10-20-01/eval_C.json`, `experiments/results/EXP-2026-10-20-01/eval_F.json`, `experiments/results/EXP-2026-10-20-01/eval_R.json`, `experiments/results/EXP-2026-10-20-01/eval_Bplus.json`, `experiments/results/EXP-2026-10-20-01/eval_Bplus0.json`, `experiments/results/EXP-2026-10-20-01/eval_v10.csv`, `experiments/results/EXP-2026-10-20-01/eval_v11.csv`, `experiments/results/EXP-2026-10-20-01/eval_Bplus.csv`, `experiments/results/EXP-2026-10-20-01/eval_Bplus0.csv`

## EXP-2026-10-20-02

Protected-loss multiplier and Kamaru Usman  
Date 2026-10-20, decision: informational, code at commit `d4a9325`.

Question. Does raising the rating engine's protected-loss multiplier (0.15 in v1.0) move a 1-4 former champion with a sticky rating?

| Method | |
|---|---|
| instrument | resume_board.build for Oct 18, 2026 (today's board) under v1.1 rules with the multiplier at 0.15, 0.30, 0.40, 0.50 |
| metric | face validity only |

Candidate. `{"engine.protected_loss_mult": [0.15, 0.3, 0.4, 0.5]}`

| Result | |
|---|---|
| Usman rating | 1812, 1807, 1803, 1799 |
| Usman position | 5 at every setting; 7 needs about 20 more points |
| why | only two of his four losses were protected non-dominant first losses (Edwards 1, Du Plessis); Edwards 2 was already charged at 60% as a second straight loss and the Chimaev loss was unprotected and short-notice |

| Face validity | |
|---|---|
| Usman (WW) | 5, 5, 5, 5 |
| Buckley | 16, 15, 15, 15 |
| Adesanya | 14 at every setting |
| Chiasson (WBW) | 8, 7, 7, 8 |

Decision. informational: The multiplier is not the lever for this case; the rating channel's stickiness for a long-reigning champion is. Logged so the lever is not retried for this purpose.

Files: `experiments/results/EXP-2026-10-20-02/anchors.log`

## EXP-2026-10-20-03

Panel comparison: v1.0 rules vs B+0 under two engines  
Date 2026-10-20, decision: informational, code at commit `d4a9325`.

Question. On a far larger instrument than the 43 boards, do the B+0 ledger and form rules change accuracy, and does protection 0.30 in the engine matter?

| Method | |
|---|---|
| instrument | board_tune panel (src/mmalab/board_tune.py): one rating pass, boards every 14 days, score order without placement rules |
| window | 2014-01-05 to 2026-10-18, 335 board dates |
| bouts | 3,656 decided bouts between two fighters on the same divisional board at the preceding date |
| metric | pairwise concordance (ties 0.5); log loss through a one-parameter logistic map fitted on the bouts being scored (in-sample) unless stated |
| baseline | v1.0 rules on the same bouts |
| interval | paired event-block bootstrap, 5,000 draws |
| engines | v1.0 engine; engine with protected_loss_mult 0.30 (separate panel each) |

Candidate. `{"B+0": "as EXP-2026-10-20-01", "engine": "protected_loss_mult 0.15 or 0.30"}`

| Result | |
|---|---|
| v1.0 engine, v1.0 rules | 0.5737 / 0.6771; top 30 0.5504; top 15 0.5434 / 0.6883 |
| v1.0 engine, B+0 | 0.5795 / 0.6746; top 30 0.5452; top 15 0.5266 / 0.6912 |
| 0.30 engine, v1.0 rules | 0.5745 / 0.6770; top 15 0.5417 |
| 0.30 engine, B+0 | 0.5806 / 0.6745; top 15 0.5296 |
| reading | B+0 helps the whole population a little and hurts the top 15 by about 1.5 points (inside noise on 960 bouts); the engine change is neutral |

Decision. informational: Both effects are small; the panel is the instrument for the walk-forward that follows. Note: these panels used the code before the dated roster files and the official-rank aliases were merged; the rebuilt panels (EXP-2026-10-20-06) supersede the absolute numbers.

Files: `experiments/results/EXP-2026-10-20-03/panel_v10.log`, `experiments/results/EXP-2026-10-20-03/panel_p30.log`

## EXP-2026-10-20-04

Walk-forward tuning of the board rules, first pass (search blind spot)  
Date 2026-10-20, decision: superseded, code at commit `d4a9325`.

Question. Tuning the ledger, horizon, form and split one coordinate at a time on every year before the test year, how much held-out accuracy is available beyond v1.0?

| Method | |
|---|---|
| instrument | board_tune panel (src/mmalab/board_tune.py): one rating pass, boards every 14 days, score order without placement rules |
| window | 2014-01-05 to 2026-10-18, 335 board dates |
| bouts | 3,656 decided bouts between two fighters on the same divisional board at the preceding date |
| metric | pairwise concordance (ties 0.5); log loss through a one-parameter logistic map fitted on the bouts being scored (in-sample) unless stated |
| baseline | v1.0 rules on the same bouts |
| interval | paired event-block bootstrap, 5,000 draws |
| protocol | test years 2017 to 2026; coordinate descent on training years (3 sweeps); slope for the test year fitted on training years only; 2,824 held-out bouts |

Candidate. `{"search space": "w_rating, horizon (steps or exponential), proof value, loss mode/tiers/extra/window/decay, hindsight mode and blends, form mode/buckets/tiers/cap/bad-loss", "full-sample fit (in-sample, for reference)": {"w_rating": 0.75, "horizon": {"kind": "exp", "full_years": 1.0, "tau": 1.5, "max_years": 15.0}, "proof_value": 0.5, "loss": {"mode": "v10", "years": 15.0, "tiers": [0.0, 1.0, 1.0, 1.0], "dominant_extra": 0.0, "decay": "flat"}, "hindsight": {"mode": "none", "alpha_win": 1.0, "alpha_loss": 1.0}, "form": {"mode": "tiered", "buckets": {"2-3": 0.15, "1-4": 0.6, "0-5": 0.8}, "tiers": [0.05, 0.1, 0.1, 0.2], "cap": 0.3, "bad_loss": {"rank_above": 10, "per_loss": 0.0, "cap": 0.3}}}}`

| Result | |
|---|---|
| held-out pooled | tuned 0.5965 / 0.6678; v1.0 0.5752 / 0.6786; B+0 0.5777 / 0.6759 |
| tuned minus v1.0 | log loss -0.0108 CI [-0.015137996315324514, -0.006406517850399804]; concordance +0.0212 CI [0.007865219362950567, 0.034810520183890664] |
| B+0 minus v1.0 | log loss -0.0027 CI [-0.004784980028257844, -0.0007599882136596996]; concordance +0.0025 CI [-0.008005575424660964, 0.012803762469526535] |
| top 15 (732 bouts) | tuned 0.5512 / 0.6768; v1.0 0.5348 / 0.6939 |
| what the data chose | rating weight 0.75; quality wins at full value for one year then exponential decay with a 1.5-year time constant; losses charged flat for 15 years; a small tiered last-five penalty (0.05 to 0.20 per loss, cap 0.30) |

Decision. superseded: Real held-out gain of about 2 points of concordance, but the search had a blind spot: the loss tiers were never tried while loss mode was v1.0, and the hindsight blends were never tried while the mode was none (a mode switch alone changes nothing, so it was never accepted). Fixed by coupling those coordinates (IMPLIES in board_tune.py); rerun as EXP-2026-10-20-06. The chosen horizon (fast decay) also conflicts with the resume principle that long resumes keep their value, which the rerun tests as a separate preset.

Files: `experiments/results/EXP-2026-10-20-04/wf_v10.json`, `experiments/results/EXP-2026-10-20-04/wf_v10_full.json`, `experiments/results/EXP-2026-10-20-04/wf_v10.log`

## EXP-2026-10-20-05

Hindsight re-grading of results (curator's idea)  
Date 2026-10-20, decision: parked, code at commit `d4a9325`.

Question. If the value of a win or the cost of a loss is graded partly by where the opponent stands now (or two years on) instead of only on fight night, does accuracy improve, and what does it do to the board?

| Method | |
|---|---|
| instrument | board_tune panel (src/mmalab/board_tune.py): one rating pass, boards every 14 days, score order without placement rules |
| window | 2014-01-05 to 2026-10-18, 335 board dates |
| bouts | 3,656 decided bouts between two fighters on the same divisional board at the preceding date |
| metric | pairwise concordance (ties 0.5); log loss through a one-parameter logistic map fitted on the bouts being scored (in-sample) unless stated |
| baseline | v1.0 rules on the same bouts |
| interval | paired event-block bootstrap, 5,000 draws |
| note | in-sample grid on top of B+0, v1.0 engine panel; then full builds of today's board for face validity |

Candidate. `{"modes": "now_official (opponent's current official rank), now_rating (opponent's current REAL rating position in the bout's division), post_rating (rating position two years after the bout)", "blends": "alpha_win and alpha_loss in {1, 0.75, 0.5, 0.25, 0}: weight on the fight-night grade"}`

| Result | |
|---|---|
| best overall | now_official, alpha 0/0: 0.5855 / 0.6720 vs B+0 0.5795 / 0.6746 (log-loss diff -0.0026, CI -0.0041 to -0.0010); top 15 0.5498 vs 0.5266 |
| now_rating 0/0 | 0.5855 / 0.6733 (diff -0.0013, CI -0.0027 to +0.0002) |
| post_rating 0/0 | 0.5841 / 0.6739 (diff -0.0007, CI -0.0020 to +0.0006) |
| pattern | every setting improves log loss; more hindsight is better; the win side carries most of it |

| Face validity | |
|---|---|
| Usman (WW) | 5 at half and full hindsight by rating; 2 at full hindsight by two-year standing |
| Buckley | 15 to 16 |
| Adesanya | 14 to 18 to 20 |
| Vera | 14 to 19 to 29 |
| Perez (FLW) | 24 to 30 |
| Turner (LW) | 23 to 28 |
| welterweight top 4 | Prates rises to 1 |

Decision. parked: Small real gain, but it does the one thing the curator ruled out: it pulls down long resumes whose opponents have since faded (Vera 14 to 29, Adesanya 14 to 20 at full hindsight by rating) and leaves Usman at 5. Kept as a measured option in the harness; it would need a form that protects aged resumes (for example hindsight for wins younger than three years only) before it could be proposed.

## EXP-2026-10-20-06

Walk-forward tuning, second pass: coupled coordinates, free and resume presets  
Date 2026-10-20, decision: informational, code at commit `d4a9325`.

Question. With the search blind spot fixed, how much held-out accuracy is available (a) with every rule free and (b) holding the resume principles fixed (quality wins keep full value for three or more years; losses count for at most six years), under the v1.0 engine and the 0.30-protection engine?

| Method | |
|---|---|
| instrument | board_tune panel (src/mmalab/board_tune.py): one rating pass, boards every 14 days, score order without placement rules |
| window | 2014-01-05 to 2026-10-18, 335 board dates |
| bouts | 3,656 decided bouts between two fighters on the same divisional board at the preceding date |
| metric | pairwise concordance (ties 0.5); log loss through a one-parameter logistic map fitted on the bouts being scored (in-sample) unless stated |
| baseline | v1.0 rules on the same bouts |
| interval | paired event-block bootstrap, 5,000 draws |
| protocol | as EXP-2026-10-20-04 on panels rebuilt after the dated roster files and official-rank aliases were merged; presets free and resume; engines v1.0 and protected_loss_mult 0.30 |

Candidate. `{"driver": "scratchpad tune_driver.py calling board_tune.walk_forward(space=default_space(preset))"}`

| Result | |
|---|---|
| free preset, held out 2017-2026 (2,903 bouts) | tuned 0.6052 / 0.6668; v1.0 0.5753 / 0.6784; B+0 0.5787 / 0.6756; tuned minus v1.0: log loss -0.0115 CI [-0.0162, -0.0068], concordance +0.0300 CI [0.0171, 0.0427]; top 15 (755): tuned 0.5669 vs v1.0 0.5364 |
| resume preset, held out 2017-2026 (2,903 bouts) | tuned 0.5911 / 0.6713; v1.0 0.5753 / 0.6784; B+0 0.5787 / 0.6756; tuned minus v1.0: log loss -0.0070 CI [-0.0108, -0.0034], concordance +0.0158 CI [0.0035, 0.0281]; top 15 (755): tuned 0.5669 vs v1.0 0.5364 |
| free full-sample fit (in-sample 0.6043 / 0.6640) | {"w_rating": 0.7, "horizon": {"kind": "exp", "full_years": 2.0, "tau": 1.0, "max_years": 15.0}, "proof_value": 0.25, "loss": {"mode": "tiers", "years": 15.0, "tiers": [0.0, 0.25, 0.5, 1.0], "dominant_extra": 1.0, "decay": "flat"}, "hindsight": {"mode": "now_official", "alpha_win": 0.5, "alpha_loss": 0.25}, "form": {"mode": "tiered", "buckets": {"2-3": 0.15, "1-4": 0.6, "0-5": 0.8}, "tiers": [0.05, 0.1, 0.1, 0.2], "cap": 0.3, "bad_loss": {"rank_above": 10, "per_loss": 0.0, "cap": 0.3}}} |
| resume full-sample fit (in-sample 0.5894 / 0.6683) | {"w_rating": 0.8, "horizon": {"kind": "exp", "full_years": 3.0, "tau": 1.0, "max_years": 15.0}, "proof_value": 0.25, "loss": {"mode": "tiers", "years": 6.0, "tiers": [0.25, 0.25, 0.5, 0.75], "dominant_extra": 1.0, "decay": "flat"}, "hindsight": {"mode": "now_official", "alpha_win": 0.25, "alpha_loss": 0.25}, "form": {"mode": "tiered", "buckets": {"2-3": 0.15, "1-4": 0.6, "0-5": 0.8}, "tiers": [0.05, 0.1, 0.1, 0.15], "cap": 0.6, "bad_loss": {"rank_above": 10, "per_loss": 0.0, "cap": 0.3}}} |
| stability of choices (free) | horizon fast decay in 9 of 10 folds; loss tiers [0, 0.25, 0.5, 0.75] in 9 of 10; loss window 10 to 15 years; hindsight now_official in all 10 folds; rating weight 0.60 to 0.65 |
| price of the resume principles | about 1.4 points of concordance and 0.0045 log loss held out (free 0.6052 / 0.6668 vs resume 0.5911 / 0.6713) |
| note | the 0.30-protection engine runs were dropped after the engine sweep (EXP-2026-10-20-07) showed the engine levers accuracy-neutral |

Decision. informational: Both presets beat v1.0 out of sample (free +3.0 points, resume +1.6 points of concordance). The free rules are recency plus hindsight plus a long memory of losses, which the curator rejects for a resume board; the resume preset keeps three-year full credit and a six-year loss memory and still gains 1.6 points, but it chose hindsight (alpha 0.25) and a 1.0 blowout surcharge, so its face validity must be checked before it becomes a v1.2 proposal. No change to v1.1.

Files: `experiments/results/EXP-2026-10-20-06/walkforward_free.json`, `experiments/results/EXP-2026-10-20-06/walkforward_resume.json`, `experiments/results/EXP-2026-10-20-06/fullfit_free.json`, `experiments/results/EXP-2026-10-20-06/fullfit_resume.json`, `experiments/results/EXP-2026-10-20-06/pooled_free.csv`, `experiments/results/EXP-2026-10-20-06/pooled_resume.csv`

## EXP-2026-10-20-07

Rating-engine sweep (K, protection, consecutive-loss rule, protection ladder, no official ranks)  
Date 2026-10-20, decision: informational, code at commit `d4a9325`.

Question. Which rating-engine settings predict better on the 2014-2026 panel with the v1.1 board rules fixed, and which of them move the anchors (Usman, Buckley, Adesanya, Vera)?

| Method | |
|---|---|
| instrument | board_tune panel (src/mmalab/board_tune.py): one rating pass, boards every 14 days, score order without placement rules |
| window | 2014-01-05 to 2026-10-18, 335 board dates |
| bouts | 3,656 decided bouts between two fighters on the same divisional board at the preceding date |
| metric | pairwise concordance (ties 0.5); log loss through a one-parameter logistic map fitted on the bouts being scored (in-sample) unless stated |
| baseline | v1.0 rules on the same bouts |
| interval | paired event-block bootstrap, 5,000 draws |
| protocol | one panel per engine variant (13), v1.0 and v1.1 rules scored on the identical bouts, paired bootstrap of the v1.1-rule log loss against the base engine; anchors read from the last panel date in score order |

Candidate. `{"variants": {"base": {}, "p30": {"protected_loss_mult": 0.3}, "p50": {"protected_loss_mult": 0.5}, "p100": {"protected_loss_mult": 1.0}, "cons100": {"consecutive_loss_mult": 1.0}, "ladder_30_60_100": {"protection_ladder": [0.3, 0.6, 1.0]}, "ladder_15_50_100": {"protection_ladder": [0.15, 0.5, 1.0]}, "k80": {"k": 80}, "k100": {"k": 100}, "k80_p30": {"k": 80, "protected_loss_mult": 0.3}, "dom100": {"dominant_loss_mult": 1.0}, "noprot": "no protection at all", "official_off": {"use_official_ranks": false}}}`

| Result | |
|---|---|
| base | v1.1 rules 0.5795 / 0.6748 (top 15 0.5343); v1.0 rules 0.5734 / 0.6772; Usman 4, Adesanya 14, Vera 14 |
| p30 | v1.1 rules 0.5811 / 0.6748 (top 15 0.5397); v1.0 rules 0.5742 / 0.6771; Usman 4, Adesanya 14, Vera 13 |
| p50 | v1.1 rules 0.5811 / 0.6746 (top 15 0.5385); v1.0 rules 0.5731 / 0.6770; Usman 4, Adesanya 14, Vera 13 |
| p100 | v1.1 rules 0.5830 / 0.6743 (top 15 0.5433); v1.0 rules 0.5760 / 0.6766; Usman 5, Adesanya 18, Vera 14 |
| cons100 | v1.1 rules 0.5800 / 0.6748 (top 15 0.5354); v1.0 rules 0.5728 / 0.6771; Usman 4, Adesanya 14, Vera 14 |
| ladder_30_60_100 | v1.1 rules 0.5795 / 0.6745 (top 15 0.5307); v1.0 rules 0.5723 / 0.6769; Usman 4, Adesanya 18, Vera 13 |
| ladder_15_50_100 | v1.1 rules 0.5814 / 0.6745 (top 15 0.5352); v1.0 rules 0.5734 / 0.6769; Usman 4, Adesanya 18, Vera 13 |
| k80 | v1.1 rules 0.5822 / 0.6743 (top 15 0.5370); v1.0 rules 0.5742 / 0.6768; Usman 4, Adesanya 14, Vera 14 |
| k100 | v1.1 rules 0.5814 / 0.6742 (top 15 0.5398); v1.0 rules 0.5737 / 0.6767; Usman 5, Adesanya 14, Vera 15 |
| k80_p30 | v1.1 rules 0.5819 / 0.6743 (top 15 0.5385); v1.0 rules 0.5747 / 0.6768; Usman 4, Adesanya 14, Vera 14 |
| dom100 | v1.1 rules 0.5811 / 0.6746 (top 15 0.5402); v1.0 rules 0.5710 / 0.6770; Usman 4, Adesanya 15, Vera 14 |
| noprot | v1.1 rules 0.5811 / 0.6740 (top 15 0.5419); v1.0 rules 0.5753 / 0.6765; Usman 5, Adesanya 20, Vera 15 |
| official_off | v1.1 rules 0.5771 / 0.6752 (top 15 0.5499); v1.0 rules 0.5715 / 0.6776; Usman 1, Adesanya 15, Vera 23 |
| reading | every engine lever is accuracy-neutral (largest log-loss change 0.0008); the protection multipliers, the ladder, K and the dominant-loss multiplier do not move the anchors except that removing official ranks (M4) puts Usman first in score order; the last six variants ran on data with five more bouts (same-name split merged mid-sweep), so their paired intervals are omitted |

Decision. informational: The rating engine's protections are a cheap resume principle in predictive terms, as section 11 of the methodology already said; nothing here changes v1.1. M4 (model positions instead of official ranks) is neutral on accuracy and remains a philosophical option for a later version.

Files: `experiments/results/EXP-2026-10-20-07/engine_sweep.csv`

## EXP-2026-10-20-08

v1.1 retrospective reconstruction (its own snapshot directory)  
Date 2026-10-20, decision: informational, code at commit `d4a9325`.

Question. Rebuilt as event-eve boards with every placement rule, what is v1.1's retrospective record on the same window as v1.0's reconstruction?

| Method | |
|---|---|
| instrument | board_versions.backfill(36) then history.validate on outputs/history_v1.1 |
| window | 127 event-eve snapshots Oct 2023 to Oct 16, 2026, plus today's |
| bouts | 973 |
| metric | concordance of the published order; log loss with the slope fitted on these snapshots (1.36 recorded in config/board_v1_1.yaml) |
| baseline | v1.0's own reconstruction (942 bouts, a different snapshot set, so not paired) |

Candidate. v1.1 as in config/board_v1_1.yaml

| Result | |
|---|---|
| primary | 0.606 (Wilson 0.575 to 0.637), log loss 0.6636 |
| top 30 | 0.564 on 484 bouts |
| top 15 | 0.533 on 246 bouts |
| title fights | 0.578 on 45 bouts |
| v1.0 reconstruction | 0.615 / 0.6669 primary; 0.544 top 15 |

Decision. informational: In-sample for both versions; the prospective record from Oct 20, 2026 is the test (PREREGISTRATION.md appendix C).

Files: `experiments/results/EXP-2026-10-20-08/forward_validation_v1_1.json`

## EXP-2026-10-20-09

Age and the rating channel: older favourites lose more often than they win  
Date 2026-10-20, decision: rejected, code at commit `ead380b`.

Question. Does the board over-rank older fighters? Split the bouts by the higher-scored fighter's age and last-five losses and see how often he wins; then test a rating discount by age.

| Method | |
|---|---|
| instrument | board_tune panel rebuilt Oct 20 (as-of roster files, official-rank aliases): one rating pass, boards every 14 days, score order without placement rules |
| window | 2014-01-05 to 2026-10-18, 335 board dates |
| bouts | 3,748 decided bouts between two fighters on the same divisional board; favourite = the higher v1.1 score |
| ages | date of birth from UFCStats (99.8% of fighter-dates) |
| metric | share of bouts won by the favourite (Wilson 95%); then concordance and log loss with the discount applied before interdecile scaling, in-sample |
| baseline | v1.1 rules (B+0) with no age term |
| interval | paired event-block bootstrap, 500 to 1,000 draws |

Candidate. `{"diagnostic": "favourite's age x last-five losses", "remedy tested": "rating - points_per_year x max(0, age - from_age), grid from_age 28 to 36, 5 to 80 points per year, plus quadratic forms"}`

| Result | |
|---|---|
| favourite 35+ (713 bouts) | won 45.2% (41.5 to 48.8) |
| favourite 35+ with 2+ losses in last five (442) | 44.6% (40.0 to 49.2) |
| favourite under 35 with 3+ losses (207) | 59.4% (52.6 to 65.9) |
| by age band, any record | under 30: 64%; 30-33: 59%; 33-36: 57%; 36+: 42 to 46% |
| overall favourite win rate | 57.8% |
| age discount 33 / 20 points per year | concordance 0.5977 vs 0.5795; log loss 0.6666 vs 0.6748 (diff -0.0082, CI -0.0108 to -0.0057); top 15 0.5581 vs 0.5343 |
| age discount 32 / 30 | 0.6102 / 0.6616 (diff -0.0132, CI -0.0182 to -0.0083); top 15 0.5728 |
| age discount 28 / 20 to 30 (best in-sample) | 0.6134 to 0.6150 / 0.6590 (diff -0.0157); top 15 0.589 to 0.598 |
| shape | the gain grows down to from_age 28 and flattens between 20 and 40 points per year; quadratic forms are no better |
| stability by period (favourite 35+) | 2014-2019: 45.9% of 257 (40 to 52); 2020-2026: 45.4% of 454 (41 to 50); under-35 favourites 58% and 63% |
| by division (favourite 35+) | welterweight 42% (121), heavyweight 45% (115), middleweight 48% (90), lightweight 41% (83), light heavyweight 50% (80), bantamweight 39% (61), featherweight 49% (53) |
| age difference gradient (favourite minus underdog) | favourite 5+ years younger: wins 70.0% (729); 2-5 younger 64.9% (690); within 2 years 57.3% (1,048); 2-5 older 53.6% (623); 5+ older 40.7% (627) |
| large score gaps only (above the median gap) | favourite 35+ wins 49.9% (355) against 65% for younger favourites: the board's confidence in an older fighter is worth nothing |

| Face validity | |
|---|---|
| today, 33 / 20 (mildest) | Usman 8 (v1.1: 5), Buckley 13, Edwards 7, Muhammad 14, Adesanya 25 (14), Whittaker 10, Blachowicz 34 (13), Vera 15, Ortega 26 (15), Cejudo 52, Oliveira 1, Holloway 2, Jim Miller 63 (19), Perez 27, Chiasson 7 |
| today, 32 / 30 | Usman 16, Buckley 12, Adesanya 28, Blachowicz 42, Vera 21, Ortega 35 |
| welterweight top 10 at 33 / 20 | Makhachev C, Prates, Morales, Brady, Garry, Della Maddalena, Bonfim, Edwards, Usman, Malott, Donchenko |
| conflict | the curator wants long resumes (Adesanya, Blachowicz, Ortega) to stay in the top 15; every age setting that helps accuracy moves them down |

Decision. rejected: Rejected for the board by the curator on principle (Oct 20, 2026): REAL ranks who has earned the spot as of now, not who wins next. A resume rank lags ability by construction, since a contender earns the higher spot by beating the man who holds it, and an older top-10 fighter loses more often because he is matched against the best, which is the point of the board. Predictive concordance therefore punishes the lag and is a descriptive check, not the objective (PREREGISTRATION.md section 8). The finding stays as a measured property for the paper, and age belongs in the prediction model (the shadow model carries age terms). What would change the verdict: a decision to publish a separate contender board; the age_discount option in build() and the harness remains available for that.

Files: `experiments/results/EXP-2026-10-20-09/age_grid_in_sample.csv`, `experiments/results/EXP-2026-10-20-09/age_grid_extended.csv`

## EXP-2026-10-20-10

Glicko-1 rating deviation for the resume rating: parameter derivation and calibration  
Date 2026-10-20, decision: adopted, code at commit `bde66dd`.

Question. Can a per-fighter rating deviation (RD) be attached to the resume rating that separates a one-bout newcomer from a twenty-bout veteran, and are its widths consistent with outcomes?

| Method | |
|---|---|
| instrument | src/mmalab/uncertainty.py (Glicko-1 formulas on the engine's pre-fight ratings; display only, never ordering) |
| window | all 8,950 bouts to Oct 17, 2026 (2,776 fighters); calibration on 5,817 decided bouts since 2015 |
| metric | RD distribution by career bouts; favourite win rate by standardised rating gap in 8 equal-count bins against the Glicko expectation; log loss of the plain gap vs the Glicko-shrunk gap |
| baseline | the plain 400-scale Elo expectation |
| interval | bin standard error about 0.018; mean bias standard error about 0.006 |

Candidate. `{"shipped": {"rd_start": 350, "rd_min": 40, "c_per_year": 37.3, "rule": "information balance: RD^2 added between bouts at the median cadence equals what one typical bout removes from an established fighter"}, "rejected": {"c_per_year": 130.2, "rule": "Glicko's t = 5 years from the median 10th-bout RD, iterated to a fixed point"}}`

| Result | |
|---|---|
| RD by career bouts at the fighter's last bout, c = 37.3 (median) | 1 bout 290; 2-3 bouts 228; 4-9 bouts 169; 10+ bouts 121 |
| same at c = 130.2 | 290; 247; 215; 199 (a 20-bout veteran no better measured than a 7-bout fighter: rejected) |
| today's board | rd >= 200 flags exactly the 212 fighters with 1-3 bouts plus 7 four-bout fighters; median RD 235 for top-30 slots held by fighters with 3 or fewer bouts vs 120 for 10+ |
| band width | a 1-RD band spans 5 or more positions for 99% of the board because the within-division rating SD (about 95) is about one veteran RD; median span 56 positions (42 in the top 30) |
| calibration | favourites win more often than the Glicko expectation in 7 of 8 bins (bias +0.019 at c = 37.3, +0.026 at c = 130; the plain Elo gap is unbiased at +0.003 and has the lower log loss, 0.6781 vs 0.6795 to 0.6802); gap slope 0.95 of nominal (0.87 when both fighters have 3+ bouts) |
| no-mutation check | run_resume outputs byte-identical with and without the module |

| Face validity | |
|---|---|
| Lightweight today | Oliveira 1860 RD 105 band ranks 1-4; Topuria 1792 RD 132 band 1-14; Pimblett 1720 RD 132 band 3-31; a one-bout newcomer at 1545 RD 291 spans the whole division |

Decision. adopted: RD is attached to every board row as a measurement-information statement (bouts fought, opponents' certainty, time idle) and drives nothing in the order. It is not a predictive shrinkage: applying g() to an Elo-type gap double-shrinks, and debutants are over-rated at 1500 (a bias, not a variance). Showing rank bands would mislead (almost every band spans 5+ places); the experience contrast is the usable signal and backs the provisional label.

Notes. Worth remembering: Glicko's t = 5 rule is incompatible with a usable experience gradient in UFC data (about 2 bouts a year, d of about 412 points per bout). A grace-period inflation (idle time beyond 0.5 years at c of about 146) would give both a gradient at normal cadence and a reset after a long layoff; not implemented.

## EXP-2026-10-20-11

Placement layer as one constrained order (solver) versus the sequential head-to-head and title-cycle loops  
Date 2026-10-20, decision: adopted, code at commit `13c82fa`.

Question. Do the two placement rules, applied one after the other, produce an order that satisfies their own constraints, and does solving them together change the published boards?

| Method | |
|---|---|
| instrument | src/mmalab/placement.py (priority topological sort over precedence and cap constraints collected against the score order) against resume_board.head_to_head then title_cycle, on captured build inputs |
| window | seven event-eve boards: 2024-04-14, 2024-09-15, 2025-01-19, 2025-06-29, 2025-12-07, 2026-05-10, 2026-10-20 (77 divisions, 4,862 positions, 1,155 top-15 positions) |
| metric | positions differing; constraints violated by each method; waived lifts; lifts the sequential rule applied that do not qualify against the score order |
| baseline | the sequential v1.0 loops |
| script | scripts/verify_placement.py (regenerates every table from live builds) |

Candidate. `{"semantics kept": "most recent meeting within 3 years lifts the winner directly above the loser when he sits within 3 places (6 if within a year); old close wins void the pair; a negative last five forfeits; title-cycle losers capped at 4 with their recent victims held below them", "options": "head_to_head.ride_settled (all, default), title_cycle.reserved_waives_h2h (true, default)", "cycles": "broken by dropping the oldest meeting (none in real data)"}`

| Result | |
|---|---|
| positions differing | 65 of 4,862 (33 of 1,155 top-15) across 13 of 77 divisions |
| sequential violates its own constraints | 10 cases: 6 chain inversions, 2 missed lifts, 2 caps overriding an older head-to-head |
| solver violations | 0 |
| today's lightweight | sequential: Oliveira 1, Holloway 2, Topuria 3 although Topuria knocked Oliveira out on 2025-06-28; solver: Topuria 1, Oliveira 2, Holloway 3 |
| non-qualifying lifts by the sequential rule | 6 (a lift that only qualified after an earlier lift moved the loser) |
| settled results inverted across 4,404 pairs | sequential 11, solver 6 (all six are winners held by a cap or victim rule) |
| determinism | shuffle tests over 40 random constraint sets and every real division |
| tests | 12 in tests/test_placement.py |

| Face validity | |
|---|---|
| today, v1.1 sequential vs solver | 17 positions differ, 6 in a top 15: Lightweight Topuria 3 to 1, Oliveira 1 to 2, Holloway 2 to 3; Women's Bantamweight Dumont 5 to 3, Vieira 3 to 4, Cavalcanti 4 to 5 |
| reach of transitive chains | Marco Tulio +8 at middleweight today, Castaneda +7 in Sept 2024, inherent in treating the constraints as hard |

Decision. adopted: Adopted for board v1.1 (config resume.placement: solver), amended into PREREGISTRATION.md appendix C before the first v1.1 snapshot; the sequential loops stay as v1.0's frozen rule. The solver honours the same rules without order dependence; every difference from the sequential result is a case where the sequential result broke one of its own constraints or applied a lift that did not qualify.

Files: `experiments/results/EXP-2026-10-20-11/final_verify.txt`, `experiments/results/EXP-2026-10-20-11/verify_recent.txt`, `experiments/results/EXP-2026-10-20-11/verify_none.txt`, `experiments/results/EXP-2026-10-20-11/verify_all_nowaive.txt`

## EXP-2026-10-20-12

v1.1 as shipped (loss tiers, form, protection 0.30, placement solver) on 43 full boards, corrected data  
Date 2026-10-20, decision: adopted, code at commit `d368984`.

Question. With the dated roster files, the official-rank aliases and the same-name split in place, and the placement solver included, is v1.1 at least as accurate as v1.0 on full event-eve boards?

| Method | |
|---|---|
| instrument | resume_board.build at every third event date with every placement rule applied (v1.0: sequential loops; v1.1: solver), published order |
| window | Oct 2023 to Oct 17, 2026, 43 event-eve boards |
| bouts | 979 decided bouts between two fighters on the same divisional board (973 to 979 depending on eligibility under each version; paired by bout) |
| metric | concordance of the published order; log loss with the frozen slope 1.36 |
| baseline | v1.0 on the same bouts and the same corrected data |
| interval | paired event-block bootstrap, 5,000 draws |

Candidate. config/board_v1_1.yaml as committed on Oct 20, 2026 (overrides: protected_loss_mult 0.30; loss_tiers [[5,0.25],[10,0.5],[15,0.75],[999,1.0]], dominant_extra 0; form_penalty 0.10/0.30/0.40; form_bad_loss rank_above 10, 0.10 per loss, cap 0.30; placement solver)

| Result | |
|---|---|
| v1.0 | 0.6067 / 0.6694; top 30 0.5608 / 0.6877; top 15 0.5372 / 0.7028 |
| v1.1 | 0.6057 / 0.6649; top 30 0.5642 / 0.6826; top 15 0.5488 / 0.6958 |
| paired v1.1 minus v1.0 | concordance -0.0010 (CI -0.0189 to +0.0164); log loss -0.0045 (CI -0.0093 to +0.0001); top-15 concordance +0.0000 (CI -0.034 to +0.035) on 246 bouts |

Decision. adopted: Equal measured accuracy with a small log-loss edge; v1.1 ships as the shadow resume board under appendix C (non-inferiority). Supersedes the numbers in EXP-2026-10-20-01 for the changelog.

Files: `experiments/results/EXP-2026-10-20-12/eval_v11s.json`, `experiments/results/EXP-2026-10-20-12/eval_v11s.csv`, `experiments/results/EXP-2026-10-20-12/eval_v10_corrected.json`, `experiments/results/EXP-2026-10-20-12/eval_v10_corrected.csv`

## EXP-2026-10-20-13

Literature sweep: aging, damage accumulation, style and longevity, time-varying rating models, finding the outlier  
Date 2026-10-20, decision: informational, code at commit `f763832`.

Question. What does the scholarly literature say about aging in combat sports, damage and chin degradation, style and longevity, and the predictive methods that could identify the older fighter who is done versus the one who is still elite?

| Method | |
|---|---|
| instrument | web literature review by a research assistant, every citation opened unless flagged |
| scope | peer-reviewed sports science, sports economics and statistics, plus a few evidence-carrying non-academic analyses |

Candidate. n/a (review)

| Result | |
|---|---|
| headline | the project's age gradient replicates the published MMA record (younger fighter wins 57% overall, about 70% at a 10-year gap; 37.6% win rate at 37+); peak age in combat sports about 26 to 29; individual curves vary widely around the population curve; fighter-level KO susceptibility dominates raw damage counts (Kotrba 2023); no study has used per-bout absorbed strikes longitudinally; age inside a Bradley-Terry state (Araki 2019; Baker and McHale 2024) and random slopes with shrinkage (Berry 1999; Vaci 2019) are the methods that fit |
| pitfalls | matchmaking selection, survivorship, small old-fighter samples, look-ahead, era drift in strike rates |

Decision. informational: Kept as the reference for the profile work; the full text with 60-odd references is in the results folder.

Files: `experiments/results/EXP-2026-10-20-13/literature_review.md`

## EXP-2026-10-20-14

Fighter profiles: do career statistics add to age in predicting bouts?  
Date 2026-10-20, decision: rejected, code at commit `f763832`.

Question. On top of the frozen predictive probability and the shadow model's features (age difference, over-33, layoff, debut, experience, height, five rounds), do career statistics (strikes absorbed per minute, knockdowns against, KO losses and their recency, cumulative strikes absorbed, minutes, bouts per year, debut age, years in the UFC, grappling share, trajectory of recent rating changes and surprises) improve out-of-sample prediction, overall and in bouts with an older fighter?

| Method | |
|---|---|
| instrument | src/mmalab/profiles.py walk-forward logistic layers (fit 2011 to Y-1, score Y, 2016 to 2026), nested models M0 to M3; refinements in the scratchpad grid (regularisation 2 to 20, theory-driven subsets, gradient boosting) |
| bouts | 5332 held-out bouts, 2016-01-02 to 2026-10-17; 2,717 with a fighter aged 33 or over |
| metric | log loss, Brier, accuracy; paired event-block bootstrap of the log-loss difference against M1 |
| features | src/mmalab/career_stats.py (as-of, no look-ahead; validated against UFC.com career statistics for Holloway, Nurmagomedov, Barboza, Arlovski) |

Candidate. `{"M0": "logit(p_elo) only", "M1": "M0 + shadow features", "M2": "M1 + 24 profile differences", "M3": "M2 + 9 over-33 interactions", "theory": "M1 + 11 literature-driven differences", "GBM": "histogram gradient boosting on the same columns"}`

| Result | |
|---|---|
| M1 over M0 | {'delta_log_loss': 0.02, 'ci95_event_block_bootstrap': [0.015, 0.0251]} |
| M2 over M1 (all bouts) | {'delta_log_loss': -0.0008, 'ci95_event_block_bootstrap': [-0.0044, 0.0028]} |
| M3 over M1 (all bouts) | {'delta_log_loss': -0.0031, 'ci95_event_block_bootstrap': [-0.0084, 0.0018]} |
| bouts with a fighter 33+ | M1 log loss 0.6329, M2 0.6324, M3 0.6366; M3 over M1 {'delta_log_loss': -0.0037, 'ci95': [-0.0129, 0.004]} |
| best refinement (theory subset, L2 20) | gain over M1 +0.0007 (CI -0.0014 to +0.0026) overall, +0.0010 in 2021-2026, +0.0007 in older bouts; accuracy in older bouts 64.2% vs 64.0% |
| gradient boosting | worse than the logistic M1 by 0.0035 to 0.0039 |
| by year | profile models lose in 2016-2017 (small training sets) and gain 0.002 to 0.008 per year in 2022-2026, not enough to clear the interval overall |

Decision. rejected: Career statistics as linear differences, with or without age interactions, add nothing reliable to what age, layoff and experience already say about the next result, overall or for older fighters. This agrees with Kotrba (2023): individual susceptibility dominates population damage counts. The descriptive profile (mileage, damage, style, trajectory) is still worth showing beside the resume rank for human judgment, labelled as not validated as a predictor; the next modelling attempt should follow the literature instead of linear aggregates: per-fighter random slopes with shrinkage, an age spline inside the rating state, and performance (strike differential) rather than win/loss as the outcome.

Files: `experiments/results/EXP-2026-10-20-14/profiles_report.json`, `experiments/results/EXP-2026-10-20-14/profiles_by_year.csv`, `experiments/results/EXP-2026-10-20-14/profiles_grid.csv`

## EXP-2026-10-20-15

v1.2 candidate from the resume-preset walk-forward: face validity on today's board  
Date 2026-10-20, decision: rejected, code at commit `ce2be76`.

Question. Do the rules the resume-preset walk-forward chose (rating weight 0.80, three-year full credit then fast decay, loss tiers 0.25/0.25/0.5/0.75 with a 1.0 blowout surcharge over six years, hindsight by current official rank at alpha 0.25, tiered form penalty 0.05 to 0.15) produce a board the curator would publish?

| Method | |
|---|---|
| instrument | resume_board.build for Oct 18, 2026 with the fitted parameters as overrides (plus the v1.1 engine and solver), compared with v1.1 on the anchor placements and the largest top-15 moves |
| metric | face validity only; the held-out accuracy is in EXP-2026-10-20-06 (59.1% vs 57.5% concordance) |

Candidate. `{"overrides": "weights rating 0.80; ledger proof 0.25, loss_tiers [[0,0.25],[5,0.25],[10,0.25],[15,0.5],[999,0.75]], dominant_extra 1.0, loss_decay flat; decisive_loss_years 6; horizon_decay full 3 years, tau 1.0; hindsight now_official alpha 0.25/0.25; form_loss_tiers 0.05/0.05/0.1/0.1/0.15 cap 0.6; placement solver; protected_loss_mult 0.30"}`

| Result | |
|---|---|
| Usman (WW) | 1 (v1.1: 5); without hindsight also 1 |
| Buckley | 27 (15) |
| Edwards | 9 (6) |
| Della Maddalena | 11 (7) |
| Adesanya | 21 (14) |
| Vera | 24 (14) |
| Ortega | 23 (15) |
| Blachowicz | 15 (13) |
| Derrick Lewis (HW) | 17 (7) |
| Jamahal Hill (LHW) | 27 (14) |
| Jessica Andrade (WSW) | 25 (10) |
| top-15 slots changed vs v1.1 | 131 of 180 |
| welterweight | Makhachev C, Usman 1, Prates, Morales, Garry, Brady, Bonfim, Malott, Donchenko, Edwards, Smith |

Decision. rejected: The accuracy-optimal rules inside the resume constraints are rating-heavy with a near-zero form penalty, which is the exact opposite of the curator's judgment on losing runs (Usman to 1, Buckley to 27, long resumes down). This is the matchmaking argument made concrete: the walk-forward rewards whoever the rating says is strongest, and a resume board is not that. v1.1 stays; the 1.6-point held-out gain is recorded as the measured price of the resume board's purpose. Individual pieces of the fit are not cherry-picked by taste.

## EXP-2026-10-21-01

Decline and rise index: the population age curve of the rating residual plus a shrunken per-fighter level and slope  
Date 2026-10-21, decision: adopted, code at commit `72c149d`.

Question. Given a fighter's own performances relative to what his rating implied, is he running ahead of or behind his rating and in which direction is he moving (decline and rise alike); does the individual trajectory add predictive accuracy anywhere; and what does the rating miss by age, in rating points?

| Method | |
|---|---|
| outcome | per fighter and decided bout, r = s - e: the resume engine's performance score (finishes 1/0, decisions a 50/50 blend of judges' cards and fight statistics) minus the pre-fight expectation from the two ratings plus a corner credit fitted on training rows (red corner wins 64% vs 53% expected by rating; the credit comes out at 20 to 32 points by year). Expectation from the resume rating (the board's) or the prediction Elo; second outcome the dominance-per-minute margin minus its rating-implied expectation |
| model | population curve f(age): piecewise-linear regression of r on age with knots 27/30/33/36, one per sex, training years 2011 to Y-1; individual level L_i: recency-weighted mean of (r - f) over the fighter's PRIOR bouts shrunk by lambda_level pseudo-bouts; individual slope b_i: recency-weighted slope of (r - f) on age shrunk by lambda_slope; prediction f(age) + L + b (age - mean prior age); weights 0.5 ** (years before / half_life); terms need 3 prior decided bouts; vectorised prior-bout sums equal to a plain loop to 1e-15 (tests/test_decline.py) |
| hyperparameters | grid lambda_level {4,8,16,32,64} x lambda_slope {60,200,1000,off} x half_life {1.5,2.5,4,unweighted}; for each test year the grid point with the largest cumulative held-out MSE gain over the years already tested (default for 2016) |
| tests | walk-forward by calendar year, test years 2016 to 2026, training from 2011, individual terms from each fighter's own earlier bouts including pre-2011 and earlier in the test year: (1) held-out R2 of the realized residual, curve alone and with the individual terms; (2) calibration slope of realized on predicted individual term; (3) log loss of the RESULT when the terms join the shadow model's feature set, logistic layer trained only on held-out years (2017 on), paired event-block bootstrap; (4) 33+ fighters by quartile of the individual prediction, win rate vs expectation; (5) board test on the 14-day tuning panel (335 boards, 3,748 bouts, 2014 to 2026): each board's resume ratings adjusted by the as-of index in rating points (695 per unit), concordance and log loss vs unadjusted v1.0 and B+0 rules, paired event bootstrap; the as-of index at each board date uses bouts before it only and the hyperparameters chosen for that year (default before 2017) |
| instrument | src/mmalab/decline.py (research: python -m mmalab.decline --rating resume|elo --outcome perf|margin; board test: scratchpad decline_board_test.py, copied here) |

Candidate. `{"settings frozen in config/decline.yaml": {"rating": "resume", "outcome": "perf", "lambda_level": 32.0, "lambda_slope": 200.0, "half_life": 4.0, "min_prior": 3, "points_per_residual": 694.9, "published for": "fighters with 3 decided UFC bouts and a bout in the last 3 years"}, "variants run": "resume/perf (the index), elo/perf, elo/margin"}`

| Result | |
|---|---|
| resume/perf held-out (10,702 fighter-bouts) | R2 population 0.0219, plus level 0.0226, plus level and slope 0.0236; individual correlation 0.060, calibration slope 0.62, MSE gain +0.00038 |
| resume/perf R2 of the curve by year | 0.0121, 0.0246, 0.0121, 0.0118, 0.0147, 0.0133, 0.0221, 0.0292, 0.0161, 0.043, 0.0394 |
| resume/perf individual correlation by year | 0.0017, 0.0732, 0.0652, 0.0901, 0.0958, 0.0996, 0.0803, 0.0796, 0.0673, 0.1293, 0.069 |
| resume/perf chosen hyperparameters | lambda_level 32, lambda_slope 200, half_life 4.0 in every test year from 2019 (2018: half-life 2.5; 2017: 64/off/2.5) |
| resume/perf realized residual by age (held out) | 17 to 22: realized +0.086 (curve +0.068), win rate 61% vs 53% expected; 22 to 24: realized +0.090 (curve +0.060), win rate 62% vs 50% expected; 24 to 26: realized +0.063 (curve +0.053), win rate 57% vs 50% expected; 26 to 28: realized +0.063 (curve +0.040), win rate 56% vs 49% expected; 28 to 30: realized +0.042 (curve +0.024), win rate 55% vs 49% expected; 30 to 32: realized +0.007 (curve -0.004), win rate 50% vs 49% expected; 32 to 34: realized -0.012 (curve -0.038), win rate 48% vs 50% expected; 34 to 36: realized -0.063 (curve -0.062), win rate 43% vs 51% expected; 36 to 38: realized -0.089 (curve -0.082), win rate 42% vs 50% expected; 38 to 40: realized -0.140 (curve -0.098), win rate 37% vs 53% expected; 40 to 42: realized -0.187 (curve -0.115), win rate 34% vs 57% expected; 42 to 50: realized -0.210 (curve -0.145), win rate 29% vs 56% expected |
| resume/perf decliner test | 2888 held-out bouts aged 33+: lowest quartile wins 38.0% vs 52.6% expected (-14.7/100), highest 47.5% vs 52.0% (-4.5), all 43.0% vs 52.0% (-9.0) |
| resume/perf result test (shadow model + population + level and slope vs shadow) | -0.0003 (95% [-0.0014, 0.0008]) on 4849 bouts |
| elo/perf held-out | R2 population 0.0152, plus level 0.0138, plus level and slope 0.0128; individual correlation 0.012, calibration slope 0.19, MSE gain -0.00052; 2888 held-out bouts aged 33+: lowest quartile wins 36.3% vs 47.8% expected (-11.5/100), highest 46.5% vs 52.6% (-6.0), all 43.0% vs 50.6% (-7.6); result test -0.0002 (95% [-0.0012, 0.0008]) on 4849 bouts |
| elo/margin held-out | R2 population 0.0107, plus level 0.0085, plus level and slope 0.0074; individual correlation 0.010, calibration slope 0.14, MSE gain -0.00502; result test +0.0006 (95% [-0.0008, 0.0018]) on 4849 bouts |
| board test v1.0 unadjusted | 0.5734/0.6772 (top-15 0.5436) |
| board test v1.0 + population curve x1 | 0.5875/0.6689 (conc +0.0141 CI [0.003, 0.025]; log loss -0.0083 CI [-0.0111, -0.0053]; top-15 0.5582) |
| board test v1.0 + individual x1 | 0.5744/0.6777 (conc +0.0011 CI [-0.0066, 0.0084]; log loss +0.0006 CI [-0.0008, 0.0021]; top-15 0.5551) |
| board test v1.0 + population + individual x1 | 0.5880/0.6704 (conc +0.0147 CI [0.0035, 0.0254]; log loss -0.0067 CI [-0.0095, -0.0039]; top-15 0.5663) |
| board test v1.0 + age discount 33/20 (EXP-09 style, for reference) | 0.5936/0.6676 (conc +0.0203 CI [0.0099, 0.0309]; log loss -0.0096 CI [-0.0127, -0.0064]; top-15 0.5674) |
| board test B+0 unadjusted | 0.5795/0.6748 (top-15 0.5343) |
| board test B+0 + population curve x1 | 0.5995/0.6662 (conc +0.0200 CI [0.0091, 0.0312]; log loss -0.0086 CI [-0.0115, -0.0057]; top-15 0.5630) |
| board test B+0 + individual x1 | 0.5795/0.6748 (conc +0.0000 CI [-0.0072, 0.0071]; log loss +0.0000 CI [-0.0015, 0.0015]; top-15 0.5508) |
| board test B+0 + population + individual x1 | 0.5993/0.6670 (conc +0.0197 CI [0.0091, 0.0302]; log loss -0.0078 CI [-0.0106, -0.0048]; top-15 0.5753) |
| population curve now (resume rating, men) | 22: 0.0883<br>25: 0.0699<br>28: 0.0456<br>30: 0.0216<br>32: -0.0134<br>34: -0.0461<br>36: -0.0765<br>38: -0.1116<br>40: -0.1466 |
| population curve now (resume rating, women) | 22: 0.0486<br>25: 0.0445<br>28: 0.0283<br>30: 0.0011<br>32: 0.0021<br>34: -0.0203<br>36: -0.0662<br>38: -0.0942<br>40: -0.1222 |

| Face validity | |
|---|---|
| Kamaru Usman | Recent performances run about 152 points behind the rating: fighters this age typically run 95 points behind their rating, and his own recent results put him a further 57 points behind. |
| Alex Pereira | Recent performances run about 72 points behind the rating: fighters this age typically run 93 points behind their rating, and his own recent results recover 21 of those points. |
| Jan Blachowicz | Recent performances run about 187 points behind the rating: fighters this age typically run 146 points behind their rating, and his own recent results put him a further 41 points behind. |
| Israel Adesanya | Recent performances run about 156 points behind the rating: fighters this age typically run 68 points behind their rating, and his own recent results put him a further 88 points behind. |
| Max Holloway | Recent performances run about 52 points behind the rating: fighters this age typically run 41 points behind their rating, and his own recent results put him a further 11 points behind. |
| Jon Jones | Recent performances run about 52 points behind the rating: fighters this age typically run 93 points behind their rating, and his own recent results recover 41 of those points. |
| Ilia Topuria | Recent performances are in line with the rating (+26 points). |
| Payton Talbott | Recent performances run about 59 points ahead of the rating: fighters this age typically run 31 points ahead of their rating, and his own recent results put him a further 28 points ahead. |
| Joshua Van | Recent performances run about 87 points ahead of the rating: fighters this age typically run 48 points ahead of their rating, and his own recent results put him a further 38 points ahead. |
| Charles Oliveira | Recent performances run about 34 points behind the rating: fighters this age typically run 65 points behind their rating, and his own recent results recover 31 of those points. |

Decision. adopted: Adopted as a descriptive index shown beside the rank (profile pages, outputs/decline_index.csv, outputs/decline_curve.json), with its evidence printed next to it; not adopted as a board rule and not adopted as a prediction-model feature. The population curve is the rating's age bias and is reliable: out of sample in every test year, the realized residual by age tracks the curve that predicted it (+0.09 at 22 to 24, zero at 30 to 32, -0.06 at 34 to 36, -0.14 at 38 to 40, -0.19 at 40 to 42: about +60 to -130 rating points), and converted to rating points with no free parameter it reproduces most of the age-discount gain of EXP-2026-10-20-09 on the board (+1.4 to +2.0 points of concordance). The individual terms are a weak but consistent signal against the slow resume rating (correlation 0.06 to 0.13 in 10 of 11 years; the lowest quartile of 33+ fighters wins 38% against 53% expected, the highest 48% against 52%), no signal against the fast prediction Elo, no gain in bout prediction over the shadow model, and no board accuracy beyond the curve. Nothing here enters a board: the rankings answer who deserves the place now (EXP-2026-10-20-09 decision stands).

Notes. Hyperparameters were selected online inside the walk-forward, so every held-out number is honest; the board test reuses those yearly choices (and the default before 2017), which is a mild use of 2016-era held-out information on 2014 to 2016 boards. Pre-2010 bout files list the winner first, so the corner credit is fitted on 2011+ rows only; it does not affect the symmetric residual. Beyond the last knot the curve is linear; realized held-out residuals at 40+ sit below the line, so the extrapolation is conservative. The curve is evaluated inside 18 to 45 years.

Files: `experiments/results/EXP-2026-10-21-01/decline_report_research_resume_perf.json`, `experiments/results/EXP-2026-10-21-01/decline_report_research_elo_perf.json`, `experiments/results/EXP-2026-10-21-01/decline_report_research_elo_margin.json`, `experiments/results/EXP-2026-10-21-01/decline_board_test.csv`, `experiments/results/EXP-2026-10-21-01/decline_board_test.py`, `experiments/results/EXP-2026-10-21-01/decline_index_2026-10-18.csv`, `experiments/results/EXP-2026-10-21-01/decline_curve_2026-10-18.json`

## EXP-2026-10-21-02

Who declines faster: the population curve by style, debut age, weight band, UFC tenure and recent knockout loss  
Date 2026-10-21, decision: informational, code at commit `72c149d`.

Question. Do wrestlers age better than strikers (the curator's hypothesis), and which groups of fighters run further behind their rating as they age: early debutants, lighter divisions, long tenures, fighters with a recent knockout loss?

| Method | |
|---|---|
| descriptive | men's fighter-bouts 2011 to 2026-10-17 with the resume-rating residual of EXP-2026-10-21-01, population curve (knots 27/30/33/36) fitted within each group of each grouping, curve values at 24/27/30/33/35/37/40 inside the group's central 95% of ages, event-block bootstrap (2,000 draws) for the difference between two groups at each age |
| groupings | fighting style as of the bout (career_stats thresholds): striker, wrestler, mixed | age at UFC debut: early (under 25), standard (25 to 28), late (29 or over) | weight band: light (flyweight to featherweight), middle (lightweight, welterweight), heavy (middleweight and up) | UFC tenure at the bout: under 4 years or 4 years and over | knockout losses in the previous three years: none or at least one (all as of the bout, from career_stats.bout_features) |
| out of sample | the full walk-forward of EXP-2026-10-21-01 rerun with one curve per (sex, group) where the group has 300 training rows, else the sex curve, for style and for debut age; compared with the pooled curve on held-out R2 |
| instrument | python -m mmalab.decline --rating resume --stratified; --group style; --group debut |

Candidate. `{"question": "group-specific age curves", "data": "12706 men's fighter-bouts 2011 to 2026-10-17, residual outcome as in the main run, in sample"}`

| Result | |
|---|---|
| style | groups: mixed: n: 5142<br>curve: 24: None<br>27: 0.0512<br>30: 0.0161<br>33: -0.0146<br>35: -0.0484<br>37: -0.0756<br>40: None<br>striker: n: 3194<br>curve: 24: 0.1151<br>27: 0.0739<br>30: 0.0196<br>33: -0.0475<br>35: -0.0653<br>37: -0.1005<br>40: None<br>wrestler: n: 2697<br>curve: 24: 0.0869<br>27: 0.0733<br>30: 0.056<br>33: -0.0467<br>35: -0.0812<br>37: -0.1213<br>40: None<br>contrast: striker minus wrestler<br>by_age: 24: difference: 0.0282<br>ci95: -0.0299, 0.0836<br>27: difference: 0.0006<br>ci95: -0.0499, 0.0516<br>30: difference: -0.0364<br>ci95: -0.0851, 0.0146<br>33: difference: -0.0008<br>ci95: -0.0573, 0.056<br>35: difference: 0.0159<br>ci95: -0.0243, 0.0547<br>37: difference: 0.0208<br>ci95: -0.0294, 0.0683 |
| debut | groups: early: n: 3032<br>curve: 24: 0.0783<br>27: 0.0528<br>30: 0.0087<br>33: -0.1047<br>35: -0.1079<br>37: -0.1319<br>40: None<br>late: n: 3889<br>curve: 24: None<br>27: None<br>30: 0.023<br>33: -0.0255<br>35: -0.0378<br>37: -0.0656<br>40: -0.1304<br>standard: n: 5785<br>curve: 24: None<br>27: 0.0681<br>30: 0.0231<br>33: -0.0137<br>35: -0.0923<br>37: -0.1384<br>40: None<br>contrast: early minus late<br>by_age: 30: difference: -0.0143<br>ci95: -0.0637, 0.0383<br>33: difference: -0.0792<br>ci95: -0.1356, -0.0218<br>35: difference: -0.0701<br>ci95: -0.1115, -0.0248<br>37: difference: -0.0663<br>ci95: -0.1203, -0.0095 |
| weight | groups: heavy: n: 3906<br>curve: 24: None<br>27: 0.055<br>30: 0.0546<br>33: -0.0325<br>35: -0.0406<br>37: -0.0626<br>40: -0.1164<br>light: n: 4179<br>curve: 24: 0.0798<br>27: 0.0545<br>30: -0.0085<br>33: -0.0374<br>35: -0.0811<br>37: -0.1275<br>40: None<br>middle: n: 4471<br>curve: 24: 0.0675<br>27: 0.0654<br>30: 0.0221<br>33: -0.0231<br>35: -0.0704<br>37: -0.1134<br>40: None<br>contrast: light minus heavy<br>by_age: 27: difference: -0.0005<br>ci95: -0.043, 0.043<br>30: difference: -0.0631<br>ci95: -0.1012, -0.0258<br>33: difference: -0.0049<br>ci95: -0.045, 0.0355<br>35: difference: -0.0405<br>ci95: -0.0741, -0.0054<br>37: difference: -0.0649<br>ci95: -0.108, -0.0216 |
| tenure | groups: 4 years and over: n: 4159<br>curve: 24: None<br>27: 0.0692<br>30: 0.0123<br>33: -0.0292<br>35: -0.0716<br>37: -0.1089<br>40: -0.1574<br>under 4 years: n: 8547<br>curve: 24: 0.0757<br>27: 0.0559<br>30: 0.0248<br>33: -0.0322<br>35: -0.0473<br>37: None<br>40: None<br>contrast: under 4 years minus 4 years and over<br>by_age: 27: difference: -0.0133<br>ci95: -0.073, 0.0439<br>30: difference: 0.0125<br>ci95: -0.0239, 0.048<br>33: difference: -0.003<br>ci95: -0.0401, 0.0332<br>35: difference: 0.0243<br>ci95: -0.0073, 0.056 |
| chin | groups: KO loss in 3 years: n: 4018<br>curve: 24: None<br>27: 0.0179<br>30: 0.0268<br>33: -0.0392<br>35: -0.0861<br>37: -0.1179<br>40: -0.1429<br>no KO loss in 3 years: n: 8688<br>curve: 24: 0.0701<br>27: 0.0654<br>30: 0.0205<br>33: -0.0275<br>35: -0.0381<br>37: -0.072<br>40: None<br>contrast: no KO loss in 3 years minus KO loss in 3 years<br>by_age: 27: difference: 0.0475<br>ci95: 0.0036, 0.0923<br>30: difference: -0.0063<br>ci95: -0.0452, 0.0306<br>33: difference: 0.0117<br>ci95: -0.0267, 0.0491<br>35: difference: 0.048<br>ci95: 0.0181, 0.0794<br>37: difference: 0.0459<br>ci95: 0.0091, 0.0848 |
| out of sample, curve by style vs pooled (held-out R2 of the curve) | 0.0216 vs 0.0219 |
| out of sample, curve by debut age vs pooled | 0.0213 vs 0.0219 |

Decision. informational: Findings kept, index unchanged. Strikers and wrestlers decline at the same rate (striker minus wrestler +0.016 at 35, interval -0.024 to +0.055; +0.021 at 37, -0.029 to +0.068), so the wrestlers-age-better hypothesis finds no support; the mixed group declines least. Early UFC debutants (before 25) run further behind their rating from 33 on than late debutants (29+): -0.079 at 33 (interval -0.136 to -0.022), -0.070 at 35 (-0.112 to -0.025), -0.066 at 37 (-0.120 to -0.009), about 50 rating points, consistent with mileage rather than calendar age. Lighter divisions decline harder than middleweight and above from 35 (-0.041 at 35, -0.065 at 37, intervals excluding zero). A knockout loss in the previous three years marks a further 0.05 of lag at 35 to 37. Longer UFC tenure at the same age marks more lag at 37 to 40. Fitting the curve within groups did not beat the pooled curve out of sample (style 0.0216 vs 0.0219; debut 0.0213 vs 0.0219), so the index keeps one curve per sex and the group differences stand as descriptive findings in METHODOLOGY.md section 14.

Notes. In-sample descriptive curves; selection (who is still fighting at 38) shapes every group's curve. Groups are as of the bout, so a fighter can change style or tenure group across his career.

Files: `experiments/results/EXP-2026-10-21-02/decline_report_research_resume_stratified.json`, `experiments/results/EXP-2026-10-21-02/decline_report_research_resume_perf_by_style.json`, `experiments/results/EXP-2026-10-21-02/decline_report_research_resume_perf_by_debut.json`
