# Weekly review proposal, 2026-10-26

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged. Weights, rules, thresholds and `config/weights.yaml` are unchanged (SHA-256 still `ea1a823c...5cc2`, matching the v1.0 freeze). Merging this branch approves every change below; to reject one, revert that line before merging.

Events covered: **UFC 333: Volkanovski vs. Evloev** (Abu Dhabi, Oct 24, 2026), the only event since main's data (through UFC Edmonton, Oct 17). Raw UFCStats CSVs were refreshed from Greco1899/scrape_ufc_stats; the board now runs through 2026-10-24. Next cards: UFC Fight Night Moicano vs. Nolan (Oct 31), Bonfim vs. Brady (Nov 7).

**This branch supersedes `weekly-review/2026-10-19`.** That branch was never merged and was cut from main before the dated roster format (commit fed044c), so it can no longer merge cleanly. Its config edits are carried forward here, rewritten in the dated format. Merge this branch and delete the 2026-10-19 branch.

## 1. Proposed changes

### A. Carried forward from 2026-10-19 (unmerged), now dated

| # | File | Change | Source |
|---|---|---|---|
| 1 | `config/roster_exclusions.yaml` | Farid Basharat, since 2026-10-14 (contract concluded, not renewed) | https://www.mmafighting.com/ufc/515775/farid-basharat-removed-from-ufc-roster-despite-7-0-octagon-run ; cagesidepress.com (Oct 15) |
| 2 | `config/roster_exclusions.yaml` | Ismael Bonfim, since 2026-10-12 (released after third weight miss and KO loss) | https://www.mmafighting.com/ufc/515413/ismael-bonfim-removed-from-ufc-roster-after-3rd-weight-miss-knockout-loss-to-francisco-prado ; heavy.com |
| 3 | `config/roster_exclusions.yaml` | The 32-fighter 2026 backlog (Nascimento, Vieira, Swanson, Marcos, Cowan, Bueno Silva, Fletcher, Anders, Schnell, J. Basharat, Morono, Bunes, Medina, Rowe, Mix, Burns, Lane, Gorimbo, Griffin, Gustafsson, Smotherman, Carnelossi, Moises, Harris, Waters, M. Pereira, Nicoll, Elkins, Gibson, Almakhan, Barboza, R. Oliveira) | one URL per line in the file |
| 4 | `config/short_notice.yaml` | Joel Faglier (W), Mackenzie Stiller (L), Nick Galanti (W), all 2026-10-17, 15 to 17 days notice | one URL per line in the file |

Dating rule applied: a retirement announced in the cage on fight night D takes effect D + 1; a release takes effect the day reported. Five sources give only a month (Vieira, Bunes, Medina, Waters, Nicoll), so `since` is the last day of that month and the line says "date approximate". Every exclusion was checked against the fight data: no fighter has a UFC bout on or after his `since` date.

### B. New this week

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 5 | `config/layoffs.yaml` | Petr Yan: `until: 2026-10-25` | He returned from back surgery and beat Merab Dvalishvili at UFC 333; the layoff entry closes from the first board that holds the bout | https://www.cbssports.com/ufc/news/ufc-333-fight-card-alexander-volkanovski-movsar-evloev-results-winners/ (already-cited surgery sources kept) |
| 6 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*`, `METHODOLOGY.md`, `predictions/picks.csv` | Refreshed UFCStats and rebuilt with `run_all --quick` | Adds UFC 333; grades its picks; adds `outputs/history/board_2026-10-24.csv` (and the v1.1 shadow snapshot) | Greco1899/scrape_ufc_stats |

### C. Checked, nothing to add

- **Short notice at UFC 333:** none. The one replacement, Losene Keita for the injured Arnold Allen against Aaron Pico, was reported Sept 17 to 18, about 36 days out (https://www.si.com/fannation/mma/news/ufc-333-main-card-fight-reportedly-hit-with-major-change). No missed weight reported.
- **Titles:** Volkanovski (FW) and Yan (BW) retained, which the data handles. No vacated, stripped or interim titles; no new reserved spots; no announced division moves.
- **Volkanovski:** said after UFC 333 he would retire after a fight with Justin Gaethje, win or lose (https://www.fightsports.tv/volkanovski-stops-evloev-in-round-two-calls-for-retirement-fight-with-gaethje/). Not a retirement; no entry.
- **Overturned results / drug tests:** none new.
- **Unmatched names:** the ESPN feed was unreachable from this run, so `predictions/unmatched_names.csv` was not regenerated. Chopurov is now in UFCStats; Kropschot and Gabriel Lorenco already have UFCStats pages (accents normalise); Lucia Szabova and Jose Henrique look like debutants. No alias needed.

## 2. Needs Brayton's judgment

1. **Held back, single or unapproved source:** Muhammad Naimov (FW) and Dennis Buzukja, both reported removed Oct 16 only by UFCRosterNews on X and AgentMMA (https://agentmma.com/news/91551-dennis-buzukja-removed-from-ufc-roster, no source named). Buzukja had said on Oct 7 he was "stepping back from the UFC for the time being", not leaving (https://mmasucka.com/news/dennis-buzukja-announces-ufc-break-im-stepping-back-from-the-ufc-for-the-time-being). Neither is in a top 30. Add both if you accept these sources.
2. **Still open from Oct 19:** Tecia Pennington, Luana Carolina and the other single-source departures; Darrius Flowers, Sedriques Dumas, Gianni Vazquez, Jessie Rosas Jr. left in because they fought after a reported release.
3. **Inactivity clock:** Jose Aldo (BW) crosses 540 days around Oct 31 and Julianna Pena (W-BW #8, 505 days) around Nov 28. No injury or booking found for either.
4. **Merge timing:** the Monday 13:00 UTC workflow will rebuild main with UFC 333 but without these exclusions, and will also write `board_2026-10-24.csv`. Generated outputs will then conflict. Take this branch's config, then rerun `run_all --quick` on the merge. Under PREREGISTRATION section 3, whichever 10-24 snapshot is committed first is the one that stands.

## 3. Board movements, top 15 (main -> this branch)

| Division | Fighter | Move | Cause |
|---|---|---|---|
| Bantamweight | Merab Dvalishvili | 1 -> 4 | UD loss to champion Yan |
| Bantamweight | O'Malley / Song / U. Nurmagomedov | 2/3/4 -> 1/2/3 | Each up one behind Merab's drop |
| Bantamweight | Farid Basharat | 15 -> out | Exclusion; Raoni Barcelos 16 -> 15 |
| Featherweight | Movsar Evloev | 2 -> 4 | R2 TKO loss to Volkanovski (first loss) |
| Featherweight | Diego Lopes / Jean Silva | 3 -> 2 / 4 -> 3 | Up behind Evloev |
| Featherweight | Cub Swanson | 12 -> out | Exclusion; Riley, Santos, McMillen, Mariscal up one |
| Flyweight | Ramazan Temirov | 8 -> 15 | R1 KO loss to Lone'er Kavanagh (now #26) |
| Flyweight | Tim Elliott | 14 -> 9 | No bout. His Oct 21, 2023 loss to Mokaev aged out of the 3-year loss window (weak-loss charge -2.0 -> -1.0), plus Nascimento's exclusion and Temirov's drop |
| Flyweight | Allan Nascimento | 11 -> out | Exclusion; Kara-France, Ulanbekov, Imanol Rodriguez, Lima, Hasan up |
| Heavyweight | Rizvan Kuniev | 8 -> 11 | UD loss to Volkov (Volkov stays #1) |
| Heavyweight | Pinto / Lewis / Pericic | 9/10/11 -> 8/9/10 | Up behind Kuniev |
| Light Heavyweight | Dominick Reyes | 5 -> 3 | R1 KO of Murzakanov; title-cycle placement now his |
| Light Heavyweight | Azamat Murzakanov | 7 -> 10 | Same bout |
| Light Heavyweight | Navajo Stirling | 3 -> 5 | No bout; Reyes takes the title-cycle #3 spot he held |
| Light Heavyweight | Abdul Rakhman Yakhyaev | 11 -> 9 | R1 KO of Krylov (Krylov 16 -> 44, last five 1-4) |
| Light Heavyweight | Guskov / Rountree / de Ridder | 8/9/10 -> 7/8/11 | Knock-on |
| Middleweight | Cam Rowston | 15 -> 25 | R1 submission loss to Abus Magomedov (Magomedov #17) |
| Welterweight | Mike Malott / Kamaru Usman | 10 -> 9 / 9 -> 10 | Neither fought; 0.001 apart before, the welterweight exclusions (Burns, Griffin, Morono, Gorimbo, Harris, M. Pereira) changed the division scaling |
| Women's Strawweight | Iasmin Lucindo | 9 -> 5 | UD over Nicolle Caliari; Godinez, Kline, Gomes, Thainara each down one |
| Women's Bantamweight | Ketlen Vieira | 4 -> out | Exclusion; #5 to #16 each up one or two |

Champions unchanged in every division.

## 4. Audit trail items that look wrong or need judgment

1. **Moves of more than three places without a bout:** Tim Elliott (+5) and the Welterweight swap. Elliott's is the 3-year loss window working as written. Log both under the product endpoint; no fix under v1.0.
2. **Winner below the loser he just beat:** Abus Magomedov submitted #15 Cam Rowston in R1 but sits #17 while Rowston falls to #25. His ledger still carries -2.0 for two losses outside the top 5. Correct under the rules, but it will draw questions.
3. **Women's Bantamweight shuffle** comes from the Vieira exclusion (backlog item). She is the biggest name in the backlog. Confirm you accept the May 31 approximate date.

## 5. Forward validation (outputs/forward_validation.json, prospective since Oct 1 freeze)

| Primary population | Main (19 bouts) | This branch (29 bouts) |
|---|---|---|
| REAL concordance | 47.4% | 51.7% (95% CI 34.4% to 68.6%) |
| REAL log loss | 0.766 | 0.730 |
| Results-only Elo log loss | 0.775 | 0.739 |
| Performance-adjusted Elo log loss | 0.852 | 0.787 |

Both in the top 15: 8 bouts, 75.0%. Title fights: 3 of 3. Where both fighters hold an official rank (10 bouts), the official board was concordant in 60%, REAL in 70%. Interim and descriptive only (PREREGISTRATION.md section 2).

## 6. Picks record (outputs/picks_summary.json)

- Graded 38: 18 correct, 20 incorrect (47.4%, Wilson 95% 32.5% to 62.7%); log loss 0.720 against 0.693 for a coin flip.
- UFC 333: 9 of 14 correct. Misses: Yan over Merab, Kavanagh over Temirov, Yakhyaev over Krylov, Vagaev over Malkoun, Steele over Gugnon.
- Same 38 bouts: results-only Elo 42.1% (0.699 log loss); shadow v1.1 52.6% (0.729). Market at lock, 14 bouts with odds: 71.4% (0.673) against the model's 64.3% (0.645) on those bouts.
- Pending 27. Three will void at the 10-day rule because the bouts never happened: Allen vs Pico (UFC 333; Keita replaced Allen, and the Pico vs Keita pick was graded correct), plus Horth vs Cerminara and Mahjoub vs Sutherland (Edmonton, void Oct 27).
- Void 1: Kareckaite vs Gatto (Oct 10), draw or no contest.

## 7. Not done this week

- **ufc.com/rankings could not be fetched** (the fetch needed a permission approval that no one was there to give). `data/external/ufc_media.csv` and `ufc_meta.csv` were not refreshed, so official ranks at fight time for UFC 333 still come from the Oct 3 release. This is the second week running; please paste or approve the page so the Oct 10 to Oct 24 releases can be appended.
- **ESPN schedule feed unreachable from this run**, so no new picks were locked here (the scheduled workflow locks picks on its own).
