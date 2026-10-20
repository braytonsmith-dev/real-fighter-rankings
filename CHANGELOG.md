# Changelog

Every change to a ranking rule, a data correction that moves a published number, or a change in what the site displays is
logged here with its date, its reason and the evidence behind it. The rules for making a change are in GOVERNANCE.md.
Versions follow `major.minor`: a minor version changes a rule; a patch (`1.0.1`) changes display, documentation or data
handling without changing any rule. The registered method under the pre-registered forward test is always `VERSION`.

## 1.1 (shadow board, 2026-10-20)

Status: candidate, published beside the registered v1.0 board at `docs/board_v1_1.html`, never substituted for it during
the registered period (PREREGISTRATION.md section 9 and appendix C). Configuration: `config/board_v1_1.yaml`, merged over the
frozen `config/weights.yaml` at build time; the frozen file's hash is unchanged.

Reason (audit finding 1): one loss entered three channels with opponent-blind costs, so a losing run against champions and
top contenders was punished exactly like one against mid-card opposition. Joaquin Buckley fell from 9 to 21 at welterweight
on a 2-3, Israel Adesanya sat 27th at middleweight, Jan Blachowicz 27th at light heavyweight, Marlon Vera 54th at bantamweight.

Rule changes, all opponent-aware versions of existing v1.0 rules:

| Rule | v1.0 | v1.1 |
|---|---|---|
| Ledger cost of a loss (last 3 years) | flat 1.0 for a blowout or for any loss to a fighter outside the top 5; 0 otherwise | by the winner's rank at the time: top 5 0.25, top 10 0.50, top 15 0.75, unranked 1.00; blowouts add 0 |
| Last-five record penalty | 2-3: 0.15, 1-4: 0.60, 0-5: 0.80 | 2-3: 0.10, 1-4: 0.30, 0-5: 0.40, plus 0.10 per last-five loss to an opponent outside the top 10, capped at 0.30 |
| Rating cost of a non-dominant loss to a top-3 fighter or in a title fight | 15% of the normal drop | 30% of the normal drop |

Evidence: 43 event-eve boards (947 bouts, Oct 2023 to Sept 2026) rebuilt under each candidate with every placement rule applied;
concordance of the published order with the winner was 0.606 for v1.1 against 0.608 for v1.0 and log loss 0.666 against 0.671,
differences inside noise (paired 95% intervals straddle zero), so the change is adopted for face validity at equal measured
accuracy. On the 14-day tuning panel (335 boards, 3,656 bouts, 2014 to 2026, score order without placement rules) the same rules
scored 0.581 concordance and 0.6745 log loss against 0.574 and 0.6771 for v1.0 (`src/mmalab/board_tune.py`).

Effect on the Oct 17, 2026 board: 111 of 194 top-15 slots differ in holder or position. Largest moves: Vera 54 to 14, Ortega 40
to 15, Blachowicz 27 to 13, Adesanya 27 to 14, Buckley 21 to 15; Jim Miller 11 to 19, Jalin Turner 15 to 23, Neil Magny 15 to 22.
Kamaru Usman moves from 9 to 5 at welterweight: his rating (1,807) is the division's highest because his four losses in five were
to Edwards (twice), Chimaev and Du Plessis, which the rating protects by design; the curator's own view is that 7 is closer to
right, and that gap is an open item for v1.2, not a reason to hand-place him.

Also in this release, no rule change: provisional label on every board for fighters with three or fewer UFC bouts (finding D3);
version, build commit and data date in every page footer (G4); the picks ledger records no pick when the model is within two
points of 50% (P2, appendix D) and carries a feed schema check and a cumulative-record chart (E6, G5); pytest suite and pinned
dependencies (E1, E2); dated, sourced override files read as of the board date (D2); official-rank name aliases (D1).

## Data corrections (logged as facts, not rules)

- 2026-10-20: same-name fighters split (finding D8). UFCStats gives nine display names to two fighter pages each, and the
  bout files carry only the name, so ingest merged the flyweight Bruno "Bulldog" Silva and the middleweight Bruno "Blindado"
  Silva into one 23-bout "Bruno Silva". `config/fighter_disambiguation.yaml` now assigns every bout of a shared name to one
  fighter page by division (or by explicit bout URL) and names the smaller career with a suffix; ingest stops on any shared
  name or bout the file does not settle. Effect on the Oct 17, 2026 data: the 11 middleweight bouts become "Bruno Silva
  (Blindado)" (Middleweight 79, 0-5, inactivity penalty); the flyweight "Bruno Silva" keeps 12 bouts, rating 1,480 to 1,550,
  ledger -7.05 to -3.20, Flyweight 49 to 47. Direct opponents move by at most 10 rating points (HyunSung Park +9.7, 30 to 28
  at flyweight; Naurdiev -8.0, 21 to 23, and Shara Magomedov -3.5, 17 to 20, at middleweight); 13 top-30 placements shift by
  one to three spots, no top-15 holder changes. fighters.csv gains the second page of each shared name, so Jean Silva, Michael McDonald, Mike
  Davis, Anthony Romero and Victor Valenzuela now carry their own height, reach and date of birth instead of their namesake's.
- 2026-10-20: eleven official-ranking names that never matched UFCStats spellings now match through `config/official_rank_aliases.yaml`
  (Cris Cyborg = Cristiane Justino, Jacare Souza, Costas Philippou = Constantinos Philippou, Tim Johnson = Timothy Johnson, Ulka Sasaki = Yuta Sasaki,
  Antonio Rogerio Nogueira = Rogerio Nogueira, Francisco Rivera Jr., Luis Henrique Barbosa = Luis Henrique, Magomed Bibulatov, Mara Borella,
  Bruno Gustavo da Silva = Bruno Silva); one ranked name with no UFC bouts is allow-listed. Effect: 52 bouts change the opponent rank
  recorded at fight time, 23 change their quality-win flag, one final rating moves more than 10 points (Francis Carmont, +16.8). Under
  PREREGISTRATION.md section 1 the snapshots already published stand; boards from this date on use the corrected ranks.

## 1.0.1 (2026-10-01, display and documentation only)

Weight band recomputed after the head-to-head and title-cycle rules so every published rank lies inside its own band; prediction
page and card-quality positions switched to the specification the grid selected on 2010-2019; paired bootstrap and McNemar tests,
the market comparison on the held-out overlap, the constants sensitivity table (METHODOLOGY.md section 11), PREREGISTRATION.md and
DATA_LICENSE.md added; favorites page moved out of the research navigation. 2026-10-05: pre-event picks ledger (appendix A) and the
shadow v1.1 prediction model (appendix B). 2026-10-15: AI-assistance disclosure in the README.

## 1.0 (2026-10-01)

Method frozen for forward grading. Official rank at fight time (2013 on); tiered quality wins; proof-of-concept credit for close
losses to top-5 fighters; early-finish and war rules; drug-test overturns count as losses; short-notice credit; last-five form
penalty; division, head-to-head, title-cycle and reserved-spot rules; audit trail; prediction model published separately.

## 0.x (2026-09-29 to 2026-09-30)

Composite of six percentile dimensions, replaced after review because four dimensions carried no ranking signal and losses were
counted three times.
