# Weekly review proposal, 2026-11-23

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged. Weights, rules, thresholds and `config/weights.yaml` are unchanged (frozen v1.0). Merging this branch approves every change below. To reject one, revert that line before merging.

Events covered: UFC Fight Night: Prochazka vs. Stirling (UFC Qatar, Doha, Nov 21, 2026), the only event since last week's review. Raw UFCStats CSVs were refreshed with `scripts/refresh_data.sh`. The board now runs through 2026-11-21. Next card: UFC Fight Night, Dec 5, Riyadh (Adesanya vs. Magomedov).

Branch lineage. `weekly-review/2026-11-16` (which carries `weekly-review/2026-11-09`) was never merged. This branch is built on current main (`2043b8f`) with that branch merged in, so its config entries (Thompson exclusion, Harrison layoff close, Gane override close, Alatengheili and the three 11-09 short-notice entries, the `jose henrique` alias) are carried forward unchanged; see `git show origin/weekly-review/2026-11-16:PROPOSAL.md` for their sources. Generated outputs and `predictions/picks.csv` were taken from main, then rebuilt. Merge this branch, then delete `weekly-review/2026-11-09` and `weekly-review/2026-11-16`. `mmalab.checks --ref origin/main` passes and `pytest tests` passes (245 passed, 1 xfailed).

Snapshot notes.
- `outputs/history/board_2026-11-14.csv` (and the v1.1 twin) on main, committed before UFC Qatar, is the frozen pre-event snapshot for that card and is kept exactly as on main. Last week's branch copy (with the Thompson exclusion) is not used: the event has passed and PREREGISTRATION section 3 forbids rewriting it.
- This branch adds `outputs/history/board_2026-11-21.csv` (and the v1.1 twin), the pre-event snapshot for the Dec 5 card. It should be merged before Dec 5. If the Monday workflow commits its own `board_2026-11-21.csv` to main first, keep this branch's version when resolving the conflict (it holds the Ortega and Thompson exclusions and the short-notice entries).

## 1. Proposed changes

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 1 | `config/roster_exclusions.yaml` | Brian Ortega, since 2026-11-22 | Announced his retirement in the Octagon after the UD loss to Dan Hooker. UFC.com's recap words it more softly ("believed it could be the end"); Cageside and Yahoo report it as a retirement. | https://cagesidepress.com/2026/11/21/dan-hooker-defeats-brian-ortega-who-announces-retirement-after-fight/ ; https://sports.yahoo.com/mma/article/brian-ortega-retires-from-mma-following-bloody-ufc-qatar-loss-to-dan-hooker-195550919.html |
| 2 | `config/short_notice.yaml` | John Mitchell, 2026-11-21 (W) | Late-added bout vs. Shoaib Yousaf, first reported Nov 17, 4 days notice, UFC debut. Neither fighter was previously booked, so both get entries, as with Cortes Acosta and Walker. | https://heavy.com/sports/ufc/ufc-qatar-card-gets-late-addition/ ; https://www.ufc.com/news/updates-ufc-qatar |
| 3 | `config/short_notice.yaml` | Shoaib Yousaf, 2026-11-21 (L) | Same bout. The R1 KO loss costs 0.5x. | Same |
| 4 | `config/name_aliases.yaml` | `mehemmedeli osmanli: mahammadali osmanli` | ESPN's Dec 5 spelling. UFC.com lists it as the alternate spelling of the TUF 34 finalist (UFCStats fighter-details/2bbdbc925f4323ac). | https://www.ufc.com/athlete/mehemmedeli-osmanli ; https://www.ufc.com/athlete/mahammadali-osmanli |
| 5 | `config/name_aliases.yaml` | `matthieu letho duclos: matthieu duclos` | ESPN's Dec 5 spelling. UFC.com's matthieu-letho-duclos page is Matthieu Duclos (UFCStats fighter-details/ec322adbabbfa6e7, def. Luis Felipe Dias Sept 5). | https://www.ufc.com/athlete/matthieu-letho-duclos ; https://www.espn.com/mma/fighter/history/_/id/5013686/matthieu-duclos |
| 6 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*`, `METHODOLOGY.md`, `predictions/picks.csv` (grades only) | Rebuilt with `run_all --quick` | Adds UFC Qatar and grades its picks. No new locks (the schedule feed was unreachable this run; the saved copy was used). | Greco1899/scrape_ufc_stats |

Not done: `data/external/ufc_media.csv` and `ufc_meta.csv`. The ufc.com/rankings fetch was refused again (the permission prompt went unanswered in the unattended session). I did not try another route. This is the second week in a row, so the Dec 5 card will read official ranks from the Oct 31 rows, before UFC 334 and UFC Qatar. Please append the current release by hand, or approve ufc.com for the scheduled run.

### Checked, nothing to add

- Other UFC Qatar bouts. Matthews vs. Tahir Abdullayev was set Sept 29 to Oct 1 (Abdullayev replaced Akbar Abdullaev, reportedly an announcement error), about 7 weeks out. Motta vs. Dom Mar Fan (Oct 30) and Nurgozhay vs. Lorenz (about Oct 15) were added well outside 3 weeks. Cavalcanti vs. Montague moved to UFC 335. Abdullayev missed weight (172 for welterweight) and the bout went ahead at a catchweight; no config entry exists for weight misses.
- Retirements and releases. Only Ortega. Prochazka says he will fight on. Sterling, Cannonier and Matthews have not announced anything.
- Titles. None vacated, stripped or newly won. The Nov 13 Bloody Elbow headline from last week is resolved: Joshua Van missed the UFC 334 press conference and Manel Kape took his belt off the table as a stunt. Van is still champion and defends against Kape at UFC 336 (Jan 30, 2027). https://www.givemesport.com/joshua-van-ufc-belt-stolen-press-conference-no-show-ufc/ . Prates vs. Morales for the interim WW title is still set for UFC 336. No title shot has been reserved for Vallejos or Stirling.
- Division moves. None announced. Makhachev's team is discussing middleweight (Nov 7), which is not an announcement.
- Drug-test overturns. None found.
- Unmatched names. Alik Lorenz, Shoaib Yousaf and John Mitchell were debutants and now match. Modestino Rodrigues, Ivan Gnizditskiy and Akbar Abdullaev (Dec 5) now exist in UFCStats under the same spelling and need no alias.

## 2. Needs Brayton's judgment

1. The ufc.com rankings fetch (above). Two weeks of official-rank data are missing.
2. Mitchell and Yousaf both getting short-notice entries for a late-added bout. This follows the Cortes Acosta and Walker precedent; revert item 3 if you prefer to credit only the fighter who was signed to fill a slot.
3. Still open from earlier weeks: Petersen and Petroski short-notice entries (aggregator-only sources), Grant Dawson's "OUT" tag, single-source departures (Naimov, Buzukja, Pennington and others), and Pena's inactivity clock (WBW, leaves the board at 540 days, about Nov 28, unless a documented injury is added).

## 3. Board movements, top 15 (versus main, data through Nov 14)

The config changes move no one inside the top 15 (Ortega was outside the featherweight and lightweight top 15). Every move below comes from the UFC Qatar results and the calendar.

| Division | Fighter | Move | Cause |
|---|---|---|---|
| Featherweight | Kevin Vallejos | 7 -> 1 | UD over #1 Sterling (5-0). Score order #4, head-to-head lifts him over Sterling. |
| Featherweight | Aljamain Sterling | 1 -> 2 | Same bout. He keeps the division's highest score (+1.45). |
| Featherweight | Lopes, Silva, Garcia, Murphy | each down one or two | Vallejos's rise |
| Featherweight | Zalal / Allen | 9 -> 8 / 8 -> 9 (no bout) | Reorder |
| Light Heavyweight | Navajo Stirling | 5 -> 3 | R2 KO of Prochazka (5-0) |
| Light Heavyweight | Jiri Prochazka | 4 -> 5 | Same bout. Last five now 2-3. |
| Light Heavyweight | Dominick Reyes | 3 -> 4 (no bout) | Behind Stirling |
| Flyweight | Asu Almabayev | 7 -> 3 | UD loss to Horiguchi. The close loss earns +0.5 proof of concept; score order 7 -> 6, then the title-cycle reorder places him #3. |
| Flyweight | Brandon Royval | 3 -> 7 (no bout) | Score order 6 -> 7 behind Almabayev, so the title-cycle slot passes to Almabayev |
| Flyweight | Amir Albazi | 9 -> 8 | R3 submission of Costa |
| Flyweight | Alessandro Costa | 13 -> 28 | Same bout |
| Flyweight | Kara-France 8 -> 9; Lima, Temirov, Tsuruya each up one | | Knock-on |
| Middleweight | Ikram Aliskerov / Abus Magomedov | 12 -> 11 / 11 -> 12 | Aliskerov's UD over Cannonier |
| Welterweight | Uros Medic | 16 -> 13 (no bout) | His Nov 18, 2023 submission loss to Orolbai passed the three-year loss horizon (ledger -0.5 -> +0.5) |
| Welterweight | Amosov, Magny, Fakhretdinov | each down one | Behind Medic |

Horiguchi stays #2 (score up). Lightweight's top 15 is unchanged: Hooker enters the board at #26 after beating Ortega. Champions and reserved spots are unchanged in every division.

## 4. Audit trail items that look wrong or need judgment

1. Asu Almabayev rises four places after a loss (Flyweight 7 -> 3), and Royval drops four without a bout. Both moves are correct under v1.0 (proof-of-concept credit plus the title-cycle reorder), but a loser jumping to #3 will draw questions. Royval's move is over three places without a bout and counts toward the product endpoint (PREREGISTRATION section 5).
2. Kevin Vallejos at FW #1 with score +0.75, against Sterling's +1.45 at #2. The head-to-head rule decides it. Thin resume (ledger 2.5) for a #1, but working as designed.
3. Medic +3 without a bout (calendar aging). Also counts toward the product endpoint.
4. Board quality (outputs/board_quality.json): v1.0 has 2 moves without a bout and 3 band outliers; v1.1 has 1 and 0.

## 5. Forward validation (outputs/forward_validation.json, prospective since the Oct 1 freeze)

| Primary population (both scored) | Value |
|---|---|
| Bouts | 62 |
| REAL concordance | 54.8% (95% CI 42.5% to 66.6%) |
| REAL log loss | 0.742 |
| Results-only Elo log loss | 0.730 |
| Performance-adjusted Elo log loss | 0.729 |

| Secondary population | Bouts | REAL concordance |
|---|---|---|
| Both fighters in the top 30 | 31 | 67.7% |
| Both in the top 15 | 17 | 76.5% |
| Title fights | 4 | 4 of 4 |

Where both fighters held an official rank (20 bouts), the official board was concordant in 50.0% and REAL in 70.0%. On the primary population REAL's log loss remains above both Elo baselines. These numbers are interim and descriptive only (PREREGISTRATION section 2).

## 6. Picks record (outputs/picks_summary.json)

- Graded 80: 46 correct, 34 incorrect (57.5%, Wilson 95% 46.6% to 67.7%). Log loss 0.689, against 0.693 for a coin flip.
- UFC Qatar: 4 of 8. Correct: Stirling, Aliskerov, Luna, Nurgozhay. Misses: Sterling over Vallejos, Ortega over Hooker, Matthews over Abdullayev (the model's most confident pick at 70.8%), Motta over Dom Mar Fan. Four no-picks inside the band: Albazi vs. Costa, Almabayev vs. Horiguchi, Gaziev vs. Teixeira, Yousaf vs. Mitchell.
- Same bouts (all 80): results-only Elo 50.0%; shadow v1.1 64.1% (log loss 0.679). Market at lock (48 bouts with odds): 75.0% (0.622), against the model's 62.5% (0.674) on those bouts.
- Pending 14: 12 for Dec 5, plus 2 UFC 334 locks (Sadykhov vs. Nascimento, cancelled; Yanez vs. Diaz, Yanez withdrew) that void at the 10-day rule on Nov 24.
- No-pick 7. Void 13: the eight from last week, plus the five Vegas 124 locks that voided Nov 17 as expected (Bonfim vs. Brady, Bashi vs. Brennan, Lorenco vs. Hines, Kondratavicius vs. Schultz, Parsons vs. "Jose Henrique"). The Parsons lock voided even though the `jose henrique` alias is carried on this branch. I did not trace why; worth a look if that alias was meant to let the lock grade.
