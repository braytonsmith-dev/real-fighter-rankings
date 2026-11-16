# Weekly review proposal, 2026-11-16

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged. Weights, rules, thresholds and `config/weights.yaml` are unchanged (frozen v1.0, SHA-256 still `ea1a823c...5cc2`). Merging this branch approves every change below. To reject one, revert that line before merging.

Events covered: **UFC 334: Gane vs. Hokit** (Nov 14, 2026, Madison Square Garden), the only event since last week's review. Raw UFCStats CSVs were refreshed (martj42 rankings history unchanged since last week). The board now runs through 2026-11-14. Next card: UFC Fight Night, Nov 21, Doha (Prochazka vs. Stirling).

**Branch lineage.** `weekly-review/2026-11-09` was never merged. This branch is built on current main (`9b665ef`) with that branch merged in, so its four config entries (three short-notice entries and the `jose henrique` alias) are carried forward unchanged; see `git show origin/weekly-review/2026-11-09:PROPOSAL.md` for their sources. Generated outputs and `predictions/picks.csv` were taken from main and rebuilt (the 11-09 branch had no pick rows that main lacks). **Merge this branch, then delete `weekly-review/2026-11-09`.** `mmalab.checks --ref origin/main` passes and `pytest tests` passes (245 passed, 1 xfailed).

**Snapshot notes.**
- `outputs/history/board_2026-11-07.csv` on main (committed Nov 9, before UFC 334) is the frozen pre-event snapshot for UFC 334 and was kept as is. Last week's suggestion to prefer the branch copy no longer applies: the event has passed, and PREREGISTRATION section 3 forbids rewriting it.
- This branch adds `outputs/history/board_2026-11-14.csv` (and the v1.1 twin), the pre-event snapshot for the Nov 21 card. It should be merged before Nov 21. If the Monday workflow commits its own `board_2026-11-14.csv` to main first, keep this branch's version when resolving the conflict (it holds the Thompson exclusion and the short-notice entries below).

## 1. Proposed changes

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 1 | `config/roster_exclusions.yaml` | Stephen Thompson, since 2026-11-15 | Announced UFC 334 as his last fight, then retired after the R3 spinning-kick KO of Charles Radtke. | https://heavy.com/sports/ufc/stephen-thompson-retires-after-ufc-334/ ; https://www.espn.com/mma/story/_/id/50486254/stephen-thompson-caps-career-spinning-kick-ko-ufc-334 |
| 2 | `config/layoffs.yaml` | Kayla Harrison: `until: 2026-11-15` | She returned from neck surgery and submitted Amanda Nunes (R4) in the bantamweight title bout. Closed from the first board that holds the bout, as with Petr Yan. | https://sports.yahoo.com/articles/amanda-nunes-releases-statement-following-122311594.html |
| 3 | `config/champions_override.yaml` | Ciryl Gane: `until: 2026-11-15` | His UD over Josh Hokit is an undisputed title bout in the data, which supersedes the override. The file's own instructions say to close the entry when that happens. He stays champion through the bout data, and the board is unchanged. | UFCStats event 402ea3b5ee233852 |
| 4 | `config/short_notice.yaml` | Alatengheili, 2026-11-14 (L) | Replaced Adrian Yanez (withdrew, hospitalized) vs. Juan Diaz. First reported Nov 6 by Heavy, confirmed the same day by MMA Junkie, and confirmed by the UFC on Nov 10. That is 8 days notice. He lost a UD, so the loss costs 0.5x. Diaz was already booked, so like Bashi he gets no entry. | https://sports.yahoo.com/articles/hot-prospect-gets-ufc-334-004029780.html ; https://www.ufc.com/news/updates-polymarket-ufc-334-gane-vs-hokit |
| 5 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*`, `METHODOLOGY.md`, `predictions/picks.csv` (grades only) | Rebuilt with `run_all --quick` | Adds UFC 334 and grades its picks. No new locks: the Nov 21 card was locked Nov 2. | Greco1899/scrape_ufc_stats |

**Not done: `data/external/ufc_media.csv` and `ufc_meta.csv`.** The ufc.com/rankings fetch was refused this run (a permission prompt went unanswered in the unattended session). I did not try another route, so no release was appended. Rows dated Oct 31 still serve the Nov 21 card. The post-UFC 334 release should be appended next week, or by hand. Without it, the Nov 21 bouts read official ranks from before UFC 334.

### Checked, nothing to add

- **Other UFC 334 bouts.** Almeida replaced Susurkaev against Donte Johnson about 26 days out. Sources disagree, and an Oct 8 card list may already show the pairing. Either way it falls outside about 3 weeks, so there is no entry. Sadykhov vs. Nascimento was cancelled. The other ten bouts were booked by early October. No missed weights were reported. Johnson vs. Almeida is recorded as a catchweight, and I found no reason given.
- **Retirements and releases.** Only Thompson. Amanda Nunes is not retiring ("Back in the game", Instagram, Nov 15). Jim Miller (R1 TKO loss to McKinney) has said he plans to retire in 2027, with no announcement yet. No dated roster cuts were found this week.
- **Titles.**
  - HW: Gane retained.
  - WBW: Harrison won. The board already listed her as champion, so there is no change.
  - Aspinall is still out with no return date after further damage to his right eye (Nov 16). His reserved spot and layoff stay open (https://clutchpoints.com/ufc/ufc-news-tom-aspinall-eye-injury-return-update).
  - Prates vs. Morales for the interim WW title is still set for UFC 336.
- **Division moves:** none announced.
- **Drug-test overturns:** none.
- **Unmatched names:** none new. Samuel Sanches and Carlos Calderon now match.

## 2. Needs Brayton's judgment

1. **A Bloody Elbow headline from Nov 13: "UFC champion has his title stolen after no-showing press conference featuring Pereira and Oliveira".** The page would not load, and no other source I found reports a UFC title being stripped or vacated. I made no entry. If a title was in fact taken away, it belongs in `champions_override.yaml` and possibly `interim_champions.yaml`. Please check.
2. **Still open from last week:**
   - Petersen and Petroski short-notice entries (aggregator-only sources)
   - Grant Dawson's "OUT" tag
   - Naimov, Buzukja, Pennington and the other single-source departures
   - Pena's inactivity clock (526 days, WBW #9). She leaves the board at 540 days, about Nov 28, unless a documented injury is added.

## 3. Board movements, top 15 (versus main, data through Nov 7)

The four config changes move no one inside the top 15. Thompson was outside the WW top 30 before he retired. Every move below comes from the UFC 334 results and the calendar.

| Division | Fighter | Move | Cause |
|---|---|---|---|
| Heavyweight | Josh Hokit | 2 -> 5 | UD loss to Gane in a title bout. The title-cycle rule steps him back. |
| Heavyweight | Sergei Pavlovich | 5 -> 2 (no bout) | His R1 KO loss to Aspinall (Nov 11, 2023) passed the three-year horizon. Ledger 3.95 -> 4.95. |
| Heavyweight | Johnny Walker | 6 -> 3 | Title-cycle reorder behind Hokit's loss |
| Heavyweight | Curtis Blaydes | 3 -> 6 (no bout) | Same reorder. He stays behind the recent challengers. |
| Women's Bantamweight | Bia Mesquita | 6 -> 1 | R1 submission of Macy Chiasson (4-0, W4). Score order #2, then title cycle -> #1. |
| Women's Bantamweight | Amanda Nunes | out -> 4 | Back in the eligible pool after fighting. Score order #1, then title cycle -> #4 after losing to Harrison. |
| Women's Bantamweight | Edwards, Perez, Dumont, L. Santos, Cavalcanti, Y. Santos, Pena | each down one or two | Mesquita's and Nunes's entries |
| Women's Bantamweight | Macy Chiasson | 9 -> 19 | Same bout |
| Lightweight | Jim Miller | 10 -> 34 | R1 TKO loss to Terrance McKinney. Last five now 2-3. |
| Lightweight | Padilla, Ruffy, Fiziev, Nolan, Turner, Moicano | each up one | Behind Miller's drop |
| Lightweight | Salkilld / Saint Denis | 7 -> 6 / 6 -> 7 (no bout) | Division rescaling, a margin under 0.01 |
| Middleweight | Yousri Belgaroui | 11 -> 20 | UD loss to Borralho. Borralho stays at #9. |
| Middleweight | Magomedov, Aliskerov, Page, Nickal, Susurkaev | each up one | Knock-on |
| Flyweight | Bilal Hasan | 14 -> 27 | Split-decision loss to Luis Gurule |
| Flyweight | Alessandro Costa | 17 -> 13 (no bout) | A weak loss aged out (ledger -2.0 -> -1.0). Lima 13 -> 14. |
| Featherweight | Allen / Zalal | 9 -> 8 / 8 -> 9 (no bout) | Rescaling, a margin under 0.01 |
| Women's Strawweight | Kline / Godinez, Luciano / Andrade | each one-place swap (no bout) | Rescaling |

Champions and reserved spots are unchanged in every division. Welterweight's top 15 is unchanged: Medić and Holland drew and sit at #16 and #24.

## 4. Audit trail items that look wrong or need judgment

1. **Bia Mesquita at WBW #1 with one quality win** (ledger 1.0, T10 1, rank band 1 to 5). Her score is behind Nunes, and the title-cycle rule lifts her to #1. Perez (5-0, ledger 3.5) and Dumont (ledger 3.3) sit below her. This is correct under v1.0 and thin as a resume, and it is the most visible oddity on the board this week.
2. **Amanda Nunes at WBW #4 with the division's highest score** (+1.03, against Harrison's +0.70). Her rating is far above everyone else's, and only the title-cycle rule holds her at #4. This works as designed, but it will draw questions.
3. **Moves of three or more places without a bout:** Pavlovich +3, Blaydes -3, Costa +4. Costa's move is over three and counts toward the product endpoint (PREREGISTRATION section 5). Pavlovich's and Costa's moves come from the same loss-horizon aging that moved Abus Magomedov and Denise Gomes last week.
4. **Alex Pereira at HW #4 with a score of +1.20** (equal to #1 Volkov). The title-cycle rule after his June loss to Gane holds him there. I see nothing wrong.

## 5. Forward validation (outputs/forward_validation.json, prospective since the Oct 1 freeze)

| Primary population (both scored) | Value |
|---|---|
| Bouts | 53 |
| REAL concordance | 56.6% (95% CI 43.3% to 69.0%) |
| REAL log loss | 0.733 |
| Results-only Elo log loss | 0.712 |
| Performance-adjusted Elo log loss | 0.725 |

Secondary populations:

| Population | Bouts | REAL concordance |
|---|---|---|
| Both fighters in the top 30 | 27 | 70.4% |
| Both in the top 15 | 13 | 84.6% |
| Title fights | 4 | 4 of 4 |

Where both fighters held an official rank (16 bouts), the official board was concordant in 56.2% and REAL in 75.0%. On the primary population, REAL's log loss is now above both Elo baselines. These numbers are interim and descriptive only (PREREGISTRATION section 2).

## 6. Picks record (outputs/picks_summary.json)

- **Graded 72: 42 correct, 30 incorrect (58.3%, Wilson 95% 46.8% to 69.0%).** Log loss is 0.681, against 0.693 for a coin flip.
- **UFC 334: 8 of 11 correct.**
  - The misses were Nunes over Harrison, Hasan over Gurule, and Johnson over Almeida.
  - One no-pick: Borralho vs. Belgaroui fell inside the two-point band at lock.
  - Shadow v1.1 had Harrison.
- Same bouts: results-only Elo 51.4%, shadow v1.1 62.5% (log loss 0.688). Market at lock (41 bouts with odds): 75.6% (0.625 log loss), against the model's 63.4% (0.662) on those bouts.
- **Pending 16. No-pick 3.**
- **Void 8:**
  - The four listed last week.
  - The three Vegas 123 locks whose bouts changed (Brown vs. Leal, Marshall vs. Bolanos, Bekoev vs. Petroski). These voided at the 10-day rule.
  - Medić vs. Holland (UFC 334): a majority draw.
- **Coming voids:**
  - Nov 17 (the five Vegas 124 locks named last week):
    - Bonfim vs. Brady
    - Bashi vs. Brennan
    - Lorenço vs. Hines
    - Kondratavicius vs. Schultz
    - Parsons vs. "Jose Henrique"
  - Nov 24 (two UFC 334 locks):
    - Yanez vs. Diaz: Yanez withdrew, and Alatengheili vs. Diaz was locked and graded separately.
    - Sadykhov vs. Nascimento: the bout was cancelled. This was a no-pick lock.
