# REAL Fighter Rankings v1.0: pre-registered prospective validation protocol

Posted Oct 1, 2026, before the first bout it covers. Nothing in this file may be changed after that date except the commit hash in section 1, which is filled in by the commit that publishes it. Later clarifications go in a dated appendix and never alter the endpoints, populations, baselines or tests below.

## 1. What is frozen

- Method: REAL v1.0 as written in `METHODOLOGY.md` (sections 1 to 9), generated from `config/weights.yaml`.
- Code: branch `release/v1.0`, `VERSION` = 1.0. Freeze commit on `main`: recorded in `outputs/freeze_hash.txt` by the publishing commit.
- Configuration (SHA-256 at freeze):
  - `config/weights.yaml` ea1a823c00533496e89b08afaa0869a2e71ca324584c49d05cb0c7c47be15cc2
  - `config/layoffs.yaml` 9b967f3d57a70e3522af5b5f402de07e7c4cb73d748d47ba11fd760c56cf64a1
  - `config/roster_exclusions.yaml` daf8cd02cf332ba966b55deee9bac15ae2437da9226501cfee3180f252ca0f10
  - `config/division_overrides.yaml` 39d8c1b26b97f5c0518174833d0b0b35d7b887c40c1ce32bb8a7d0877e3938a1
  - `config/reserved.yaml` 8b2e05aaa0c05df38dc15ad8073a2b6b5231b3160324cb263ac520c38fa4c344
  - `config/champions_override.yaml` 050f04778271adcd5af255d25dcb93576d00256975e1d374b203771eac491092
  - `config/interim_champions.yaml` 69c13247581f24b773560d837514f7a446fd79e4144d8f310c2fcc48011dffd0
  - `config/short_notice.yaml` 1efffe100c0e09bef257e50e4c3cab50cf1ecd445d8baa7291fe20dd0db3dfaf
- The manual files above may gain entries during the evaluation period (a new injury, a retirement, a short-notice bout) because they record facts, not method. Every addition is logged in the weekly commit with its source. No v1.0 parameter, threshold, weight, alias rule or placement rule is changed for evaluation purposes. If a demonstrable source error is corrected, the original frozen prediction stands in the primary analysis and the corrected one is reported as a sensitivity result.
- The predictive model is frozen at the parameters in `outputs/backtest_report.json` (`tuned_params`, selected on 2010-2019) and at `classic_tuned_params` for the results-only baseline. Neither is refit during the period.

## 2. Evaluation period

Primary endpoint period: every eligible UFC bout from Oct 2, 2026 through Sept 30, 2027 inclusive. No test is declared final before Oct 1, 2027. Any earlier figure, including anything in a December 2026 manuscript, is labelled interim and descriptive.

## 3. Pre-event snapshot

The weekly rebuild (`.github/workflows/weekly.yml`, Mondays 13:00 UTC) writes `outputs/history/board_<date>.csv` with every eligible fighter's division, score, rank and placement flags and commits it before the next event. Predictions for an event are read from the last snapshot committed before that event's date. A snapshot is never rewritten after its event.

## 4. Populations

Primary: every completed UFC bout in a ranked division, excluding no-contests and draws, in which both fighters appear in the pre-event snapshot for that division. Eligibility is the v1.0 rule (at least one UFC bout; last appearance within 540 days, or 730 with a documented injury; not retired or released). It is not conditioned on either fighter being in a displayed top 30.

Secondary, reported but never used to declare success: both fighters in the displayed top 30; both in the top 15; both ranked by the official UFC or Meta board; title fights; bouts where either fighter has three or fewer UFC bouts; women's divisions; decisions versus finishes.

Fighters who are released, retire, move division or are injured after a snapshot remain in that snapshot as recorded. Later roster information never changes earlier eligibility.

## 5. Endpoints

Primary ranking endpoint: pairwise concordance, the share of primary-population bouts won by the fighter placed higher in the pre-event snapshot (title holders first, then published position, including positions beyond the displayed 30). Two title holders, or equal positions, count 0.5.

Probability endpoint: win probability for the first-listed fighter p = 1 / (1 + exp(-1.36 x (score_a - score_b))), the one-parameter symmetric logistic map fitted on Oct 1, 2026 to the 942 bouts between two scored fighters across the 127 reconstructed boards from Oct 2023 to Sept 2026 (retrospective log loss 0.667; on the same bouts the published order was concordant with the winner in 61.5%). The slope 1.36 is frozen and scored prospectively by log loss, Brier score, calibration intercept and slope, and an equal-count reliability table.

Product endpoints (auditability, not accuracy): weekly rank turnover; number of moves of more than three places without a new bout; number of placements outside their own weight band; number of head-to-head or title-cycle conflicts; number of manual overrides added.

## 6. Baselines, all scored on exactly the same bouts

| Baseline | Role |
|---|---|
| 50/50 | naive probability |
| Results-only Elo, frozen `classic_tuned_params` | does the resume board add anything to plain strength |
| Performance-adjusted Elo, frozen `tuned_params` | the strongest internal predictive benchmark |
| Official UFC or Meta rankings, where both fighters are ranked | the industry board |
| Closing market favorite and de-vigged closing probability, where a lawfully usable odds series exists | classification and probability benchmarks |

## 7. Statistical tests

- Concordance versus each baseline: exact McNemar test on discordant bouts, with the risk difference and a paired bootstrap interval.
- Log loss and Brier versus each baseline: mean paired difference with a 95% interval from 10,000 event-block bootstrap replicates (events resampled whole); calendar-block and fighter-cluster sensitivity analyses.
- Multiple comparisons: Holm's method across the baselines; raw and adjusted p-values both reported.
- No unpaired two-proportion tests between models scored on the same bouts.

## 8. Success criteria

v1.0 is not called validated for exceeding 50%. Evidence of incremental value requires a positive paired concordance difference against results-only Elo or the official board with a 95% interval excluding zero on the shared bouts, or a lower prospective log loss than the prespecified comparator. Failure to beat the predictive model is not failure of a resume construct, but the board must then be described as a normative resume ranking rather than empirically superior ranking technology.

## 9. Development firewall

v1.1 may be developed at any time. Its boards are published only under `shadow_v1.1` labels and are never substituted for v1.0 during the period. v1.1 is adopted only after it meets its own pre-registered criterion, written before its first shadow snapshot.

## 10. Public reporting

After each event the weekly rebuild appends to `outputs/forward_validation.csv` the snapshot date, the bout, both pre-event positions and scores, the frozen baseline predictions where available, the winner, and the inclusion or exclusion reason. The Oct 2027 report is generated from those files by `src/mmalab/history.py` without manual bout selection.

## Appendix A (added Oct 5, 2026): pre-event publication of the predictive model's picks

This appendix adds a publication mechanism. It changes no endpoint, population, baseline or test above.

1. Source of the schedule: ESPN's public UFC schedule feed (names, dates, weight classes only). Contender Series and Road to UFC cards are excluded.
2. Lock rule: the first automated run (Mondays and Fridays, 13:00 UTC) that sees a scheduled bout inside the next 21 days writes one row to `predictions/picks.csv` with the frozen performance-adjusted Elo probability (`tuned_params`), the results-only Elo probability, the REAL board probability where both fighters hold a place on the same divisional board, the pick, the confidence band, a provisional flag (either fighter with three or fewer UFC bouts), and the UTC timestamp. Rows are never edited; the file's git history is the timestamp proof. A fighter with no UFCStats history is rated 1500 and the row says so.
3. Grading: a pending pick is matched to a UFCStats result within three days of the scheduled date by the normalised name pair. Correct or incorrect follows the pick; draws and no contests are void; a pick with no matching result ten days after the event date is void (the bout fell through or a name did not match) and is listed for review.
4. Reporting: `outputs/picks_summary.json` and `docs/picks.html` carry the running record with a Wilson interval, log loss and Brier score, calibration by stated confidence band, per-event results, and the two baselines scored on exactly the same graded bouts. The ledger is a product-level record of the predictive model; the primary endpoints of this protocol remain those in sections 4 to 8 and are computed from `outputs/forward_validation.csv`.
