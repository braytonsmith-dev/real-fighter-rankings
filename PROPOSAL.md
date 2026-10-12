# Weekly review proposal, 2026-10-12

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged; weights and rules are unchanged (method v1.0 frozen). Merging this branch approves every change below; to reject one, revert that file before merging.

Events covered: **UFC Fight Night: Allen vs. Duncan** (UFC Vegas 122, Oct 10, 2026), the only event since the last data refresh (main runs through UFC 332, Oct 3). Raw UFCStats CSVs were refreshed from Greco1899/scrape_ufc_stats; the board now runs through 2026-10-10.

**This branch supersedes `weekly-review/2026-10-05`.** That proposal was never merged, so its config edits (changes 1-8 below, unchanged) are carried forward here. Merge this branch and delete the 2026-10-05 branch; merging both would only conflict on generated outputs.

## 1. Proposed changes

### Carried forward from the 2026-10-05 proposal (unchanged, still unmerged)

| # | File | Change | Source |
|---|---|---|---|
| 1 | `config/champions_override.yaml` | Remove `Women's Flyweight: VACANT` (Natalia Silva won the vacant title at UFC 332) | https://sports.yahoo.com/articles/ufc-332-results-full-card-114845804.html |
| 2 | `config/champions_override.yaml` | `Heavyweight: VACANT` -> `Heavyweight: Ciryl Gane` (promoted from interim) | https://khelnow.com/ufc/has-ciryl-gane-been-promoted-to-heavyweight-champion-ahead-of-ufc-334-202609 |
| 3 | `config/interim_champions.yaml` | Remove Gane (file now `{}`) | same as 2 |
| 4 | `config/roster_exclusions.yaml` | Add Court McGee (retired after UFC 332) | https://www.si.com/fannation/mma/news/25-fight-ufc-veteran-confirms-retirement-after-knockout-loss-at-ufc-332 |
| 5-7 | `config/short_notice.yaml` | Luis Hernandez (Sept 26), Anthony Romero and Bruce Whitehead (Oct 3) | see entries in the file |
| 8 | `data/external/ufc_media.csv` | Gane row: champion, not interim | https://www.ufc.com/rankings |

### New this week

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 9 | `config/roster_exclusions.yaml` | Add Gerald Meerschaert | Announced his retirement in the cage after his R2 TKO loss to Julius Walker on Oct 10 ("Can't fight forever"). No visible board effect. | https://www.mmanews.com/article/gerald-meerschaert-retires-ufc-vegas-122-60-fights ; https://sports.yahoo.com/articles/ufc-veteran-retires-60-fights-010539220.html |
| 10 | `config/roster_exclusions.yaml` | Remove Niko Price | The entry said he retired Mar 28, 2026. He came back, beat Leon Shahbazyan by R1 TKO on Oct 10, and then walked back his plan to retire again. No visible board effect (Welterweight, last five 1-4). See section 2. | https://heavy.com/sports/ufc/niko-price-returns-after-brief-retirement/ ; https://www.rotowire.com/mma/player/niko-price-1044 |
| 11 | `config/short_notice.yaml` | Brendson Ribeiro, 2026-10-10 (win) | Replaced Alexander Poppeck against Felipe Franco. First reported Sept 29, about 11 days out. Won by R1 guillotine. (Ismael Bonfim's replacement of Artur Minev was reported Sept 10, 30 days out, so it was not added.) | https://www.fightbookmma.com/ufc-meta-apex-allen-duncan-moicano-nolan-bonfim-brady/ ; https://en.wikipedia.org/wiki/UFC_Fight_Night:_Allen_vs._Duncan |
| 12 | ~~`config/layoffs.yaml`~~ | **Withdrawn at Brayton's direction (Oct 12).** Yair Rodriguez last fought Apr 12, 2025 and has no booking, so he drops off the board under the 540-day rule like anyone else who is not fighting. | n/a |
| 13 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*`, `predictions/picks.csv` | Refreshed UFCStats data and rebuilt with `run_all --quick` | Adds UFC Vegas 122. The picks step graded the 12 locked picks for that card (no new picks were written; the schedule feed was unreachable, so the saved copy was used). | Greco1899/scrape_ufc_stats |

### Added in the second pass (Oct 12, evening run)

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 14 | `data/external/ufc_media.csv`, `data/external/ufc_meta.csv` | Appended the ufc.com release dated Oct 3, 2026 (as_of 2026-10-03), keeping the Sept 26 rows | The morning run could not fetch ufc.com. This release (Silva champion at 125, Talbott up five at 135, Saidov and de Ridder new at 205, Zhelezniakova new at women's 135) was the live one for UFC Vegas 122. Women's Flyweight lists a tie at #6 (Jasudavicius, Barber), stored as two rank-6 rows. Gane stored as champion (visible label; only a stale photo caption says interim). | https://www.ufc.com/rankings |
| 15 | `src/mmalab/compare.py`, `src/mmalab/publish.py` | When an external file holds several dated snapshots, keep only the latest per division (two lines each) | Fixes the snapshot problem flagged on Oct 5: `official_ranks.py` already reads every dated snapshot, so Sept 26 still serves UFC 332 bouts and Oct 3 serves Vegas 122, but the comparison pages would have double-counted. It also removes an existing double-count: `fightmatrix.csv` already held five dated snapshots, which is why Patricio Pitbull showed "Fight Matrix, Fight Matrix" in the old vast-deviation table. Loading code only; no weight or rule changes. | n/a (code) |
| 16 | `config/layoffs.yaml` | Add Kayla Harrison | Neck surgery for herniated discs in Jan 2026 forced her out of UFC 324 (Jan 24); coach says she is back in full training and targeting UFC 334, Nov 14, 2026. Without this, the Women's Bantamweight champion would cross the 540-day line around Nov 29. | https://www.lowkickmma.com/kayla-harrison-withdraws-from-ufc-324-following-neck-surgery-against-amanda-nunes/ ; https://heavy.com/sports/ufc/kayla-harrison-ufc-334-return-date/ |

Effect of 14-16 on the boards: no top-15 position changes in any division. Harrison's score rises 0.44 -> 0.58 (inactivity penalty removed; she stays C). Alice Pereira's Oct 10 win over Zhelezniakova now counts as a top-15 win (she was #15 on the Oct 3 release), so her ledger goes -1.0 -> -0.5; she stays #11. Forward-validation headline numbers are unchanged; one row in `forward_validation.csv` now records Zhelezniakova's official rank as 15 instead of unranked.

### Added at Brayton's direction (Oct 12, night)

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 17 | `src/mmalab/rankings.py` | **Bug fix: a champion override can no longer outlive a title bout.** Each entry in `champions_override.yaml` must now carry `since YYYY-MM-DD`. Any undisputed title bout in the data after that date supersedes the entry, and the build prints a reminder to delete it. An entry without a date stops the build with a clear error. Entries dated after the build date are ignored, so historical rebuilds see the state as of their own date. | Root cause of the Women's Flyweight problem: the old code applied overrides after the data, unconditionally. `Women's Flyweight: VACANT` therefore beat Natalia Silva's UFC 332 title win, so main shows the title vacant with Shevchenko (R) on top. Tested: re-adding `Women's Flyweight: VACANT since 2026-09-15` now yields Silva as champion with the supersede warning; an undated entry raises the error. | n/a (code) |
| 18 | `config/champions_override.yaml`, `README.md` | Heavyweight entry dated (`Ciryl Gane since 2026-09-20`); header and README explain the date rule | Required by 17. If Gane loses to Hokit at UFC 334, the data will crown Hokit without anyone editing the file. | Dana White, UFC 331 presser (source already in the entry) |

**Women's Flyweight on this branch:** C Natalia Silva, R Valentina Shevchenko, then 1 Alexa Grasso, 2 Manon Fiorot. Main still shows "(title vacant)" until this branch is merged.

## 2. Needs Brayton's judgment

- **Yair Rodriguez:** resolved. Change 12 withdrawn; he is off the Featherweight board until he fights.
- **Niko Price (change 10).** RotoWire says he "sort of walked back" retiring, with no confirmation either way. Removing the exclusion is accurate today (he fought on Oct 10). If he confirms retirement, re-add him.
- **Kayla Harrison (change 16)** is now covered by a documented layoff. **Julianna Pena (#9, 491 days)** and **Jose Aldo (Bantamweight #13, 519 days)** are not: no reputable source found for an injury or booking. Aldo drops off around Oct 31 and Pena around Nov 28 unless they fight.
- **Change 15 is a small code edit**, not config. It is outside the usual config-only scope, so review it on its own; reverting it would restore the Fight Matrix double-count and double the UFC rows once both snapshots are present.
- **Last week's open items** (Rafael dos Anjos retirement, Jacobe Smith short notice, Aspinall and Shevchenko reserved spots) are unchanged and still need a decision.

## 3. Board movements, top 15 (main -> this branch)

| Division | Fighter | Main | Branch | Cause |
|---|---|---|---|---|
| Heavyweight | Ciryl Gane | IC | C | change 2 |
| Women's Flyweight | Natalia Silva | 3 | C | change 1 |
| Women's Flyweight | Namajunas, Blanchfield, Barber, Jasudavicius, O'Neill, Wang Cong, Judice, Maverick, Barbosa, Tarin, Cortez, Aldrich, Horth | 4-16 | 3-15 | each up one as Silva leaves the numbered board |
| Women's Flyweight | Melissa Gatto | WBW 13 | WFW 16 | majority draw with Kareckaite at 125 moved her division |
| Featherweight | Yair Rodriguez | 7 | off | last bout Apr 12, 2025 (548 days); no layoff entry, so the 540-day rule removes him |
| Featherweight | Kevin Vallejos / Arnold Allen | 8 / 9 | 7 / 8 | knock-on of Yair leaving; Jean Silva, Garcia and Murphy hold 4, 5, 6 |
| Middleweight | Brendan Allen | 4 | 3 | R5 RNC of Christian Leroy Duncan |
| Middleweight | Nassourdine Imavov | 3 | 4 | passed by Allen; no bout |
| Women's Strawweight | Loopy Godinez | 9 | 5 | UD over Ketlen Souza; last five improves to 3-2, so the form penalty drops |
| Women's Strawweight | Kline, Gomes, Lucindo | 5, 6, 7 | 6, 7, 9 | knock-on |
| Women's Bantamweight | Alice Pereira | 16 | 11 | R1 doctor-stoppage TKO of Daria Zhelezniakova |
| Women's Bantamweight | Michelle Montague, Karol Rosa | 11, 12 | 12, 13 | knock-on |
| Bantamweight | Marcus McGhee / Montel Jackson | 8 / 7 | 7 / 8 | rescale only (scores 0.549 vs 0.542); no bouts |
| Bantamweight | Brady Hiestand / Jose Aldo | 13 / 12 | 12 / 13 | Aldo's inactivity penalty grows (42 -> 44) |

Brayton's favorites: **Lerone Murphy** stays at 6 and **Nassourdine Imavov** (HM) goes 3 -> 4; neither fought. No other listed favorite moved.

## 4. Audit-trail items that look wrong

1. **Swaps with no bouts again.** McGhee/Jackson and Zalal/Allen traded places only because the division's scale moved. Same instability flagged last week (interdecile rescaling); worth a tie-tolerance rule in v1.1.
2. **Ketlen Vieira, Women's Bantamweight #4 (score order #9).** A single head-to-head lift moves her five places. Within the 6-place rule for a fight in the last 12 months, but it is the largest single lift in any top 15.
3. **Alonzo Menifield (LHW #13, score #17) and Yaroslav Amosov (WW #15, score #19).** Both lifted four places by head-to-head and both carry the widest weight-sensitivity bands in the top 15 (13-24 and 15-23). They are the least stable entries on their boards.
4. **Kamaru Usman, Welterweight #10, last five 1-4.** The only negative-form fighter in any top 10. It is rule-consistent (penalty 0.60 applied); noted for visibility.
5. **Josh Hokit, Heavyweight #2 (score #6).** Unchanged from last week; still rests on head-to-head plus the title cycle.

## 5. Forward validation (`outputs/forward_validation.json`)

Prospective since the v1.0 freeze (Oct 1), now UFC 332 plus UFC Vegas 122. The sample is still far too small to read anything into.

| Block | Bouts | REAL concordance (Wilson 95%) | REAL log loss | Results-only Elo | Perf-adjusted Elo | Official board, same bouts |
|---|---|---|---|---|---|---|
| Primary: both scored | 14 | 57.1% (32.6% to 78.6%) | 0.7005 | 0.7416 | 0.8209 | 3 both ranked: official 66.7%, REAL 100% |
| Both in top 30 | 6 | 66.7% (30.0% to 90.3%) | 0.6152 | 0.6579 | 0.7289 | 2: both 100% |
| Both in top 15 | 2 | 100% (34.2% to 100%) | 0.4551 | 0.4415 | 0.7279 | 2: both 100% |
| Title fights | 1 | 100% | 0.4373 | 0.4135 | 0.6160 | 1: correct |

Retrospective reconstruction (129 snapshots, in-sample, unchanged): 942 bouts, 61.5% concordance (58.3% to 64.5%), log loss 0.6669 against 0.6726 results-only Elo and 0.6498 performance-adjusted Elo.

Pre-event picks for UFC Vegas 122 were graded in `outputs/picks_summary.json` (one draw voided).

## 6. Merge note

Merging this branch approves changes 1-11 and 13-18 (12 is withdrawn). Then delete `weekly-review/2026-10-05`.
