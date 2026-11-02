# Weekly review proposal, 2026-11-02

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged. Weights, rules, thresholds and `config/weights.yaml` are unchanged (frozen v1.0). Merging this branch approves every change below. To reject one, revert that line before merging.

Events covered: **UFC Fight Night: Moicano vs. Nolan** (UFC Vegas 123, Oct 31, 2026), the only event since UFC 333. Raw UFCStats CSVs and the martj42 rankings history were refreshed. The board now runs through 2026-10-31. Next card: UFC Vegas 124, Nov 7 (new headliner Cortes Acosta vs. Johnny Walker).

**Branch lineage.** This branch is built on `weekly-review/2026-10-26`, which was never merged. Its config edits and your Oct 26 favorites commits are carried forward unchanged. It also merges main and `fix/official-rank-alias-saidov` (PR #3, which fixes the failing weekly-boards workflow). **Merge PR #3 first, then this branch, then delete the 2026-10-19 and 2026-10-26 branches.** The 2026-10-24 and 2026-10-31 snapshots and the locked picks come from main and PR #3 respectively. Those were committed first and stand under PREREGISTRATION section 3. `mmalab.checks --ref HEAD` passes.

## 1. Proposed changes

### A. Carried forward from 2026-10-26 (unmerged, unchanged)

The 2026-10-26 proposal items 1 to 7 are carried forward. They are the dated roster exclusions (Farid Basharat, Ismael Bonfim and the 32-fighter 2026 backlog), the short-notice entries for Faglier, Stiller and Galanti, the Petr Yan layoff closing on 2026-10-25, and your favorites list changes. Sources are in each entry. See `git show origin/weekly-review/2026-10-26:PROPOSAL.md` for the full table.

### B. New this week

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 1 | `config/official_rank_aliases.yaml` | `Muhammad Said: Muhammad Saidov` | This line arrives via PR #3, not this branch's own edit. martj42 added the Oct 6 to 20 releases, which spell the LHW #13 "Muhammad Said". UFCStats uses the same ID (b01a5e0dcd9f231d) for "Muhammad Saidov". The mismatch stopped every weekly-boards run since Oct 30. | UFCStats fighter-details/b01a5e0dcd9f231d |
| 2 | `config/roster_exclusions.yaml` | Julian Erosa, since 2026-11-01 | He announced beforehand that UFC Vegas 123 would be his last fight, win, lose or draw. He won by R1 KO over JeongYeong Lee. | https://sports.yahoo.com/articles/julian-erosa-retires-ufc-vegas-021852442.html ; https://mmasucka.com/news/julian-erosa-retires-after-first-round-knockout-of-jeongyeong-lee-at-ufc-vegas-123 |
| 3 | `config/short_notice.yaml` | Jacobe Smith, 2026-10-31 (W) | He replaced the injured Carlos Leal against Randy Brown in the co-main. The change was reported the evening of Oct 19, which is 12 days notice. He won by UD. | https://heavy.com/sports/ufc/jacobe-smith-accepts-ufc-vegas-123/ ; https://www.si.com/fannation/mma/news/undefeated-ufc-finisher-makes-quick-return-to-save-co-main-event-fight-on-halloween |
| 4 | `data/external/ufc_media.csv`, `ufc_meta.csv` | Appended the ufc.com release labeled "Last updated: Saturday, Oct. 24" (as_of 2026-10-24, 176 rows each) | This is the first successful fetch in three weeks. Gane is stored as champion, not interim, as in prior weeks: only the image alt text says interim. The media panel has two ties at #12 (WW: Buckley, Medić; HW: Fortune, Lewis), stored as two rank-12 rows. | https://www.ufc.com/rankings |
| 5 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*`, `METHODOLOGY.md` | Rebuilt with `run_all --quick` | Adds UFC Vegas 123 and grades its picks | Greco1899/scrape_ufc_stats, martj42/ufc_rankings_history |

Note on item 4: ranks are read strictly before the fight date, so the Oct 24 rows serve Vegas 123 bouts and later. They do not serve UFC 333. The **Meta** list clearly includes UFC 333 results (Reyes up 3, Murzakanov down 5, Kuniev down 2), so it must not be backdated. The **media panel** shows only post-Edmonton movement (Malott up 3, Buckley down 2), so it was probably the list in effect going into UFC 333. martj42 now covers through Oct 20, so UFC 333 bouts use its Oct 20 release, which is the right one.

### C. Checked, nothing to add

- **Other Vegas 123 changes:** Ortega's withdrawal was replaced by Tom Nolan on Sept 14 (47 days out), which is not short notice. No missed weights or overturned results were found. Moicano disputed the stoppage, but the result stands.
- **Titles:** none vacated, stripped or newly won. Makhachev declined a January booking, and the UFC announced Prates vs. Morales for an **interim welterweight title at UFC 336** (https://mmasucka.com/news/matt-brown-slams-ufc-336-interim-title-islam-makhachev/). No entry is needed until the bout happens. Makhachev is not injured, so he gets no layoff entry.
- **Retirements and releases:** only Erosa. roster.watch shows no removals Oct 19 to Nov 2.
- **Division moves:** none announced.
- **Drug-test overturns:** none new.
- **Unmatched names:** Szabova and Kropschot debuted and now match. Marcos Degli, Samuel Sanches and Gabriel Lorenço all have UFCStats pages under those spellings, so no alias is needed. Jose Henrique looks like a debutant.

## 2. Needs Brayton's judgment

1. **UFC Vegas 124 main event change.** Sean Brady withdrew injured (reported Oct 29), and Cortes Acosta vs. Johnny Walker is the new headliner (https://cagesidepress.com/2026/10/29/ufc-vegas-124-loses-bonfim-vs-brady-heavyweight-headliner/). The feed now lists the card twice under two names. The Bonfim vs. Brady pick will void at the 10-day rule. Both headliners took the fight about 9 days out. If that is confirmed, next week's review will add short-notice entries after the bout. Brady (WW #2, 176 days) needs no layoff entry yet.
2. **Still open from earlier weeks:** Naimov and Buzukja (single-source releases), Pennington and the other single-source departures, and Aldo's and Pena's inactivity clocks. Miesha Tate dropped out of the WBW top 30 this week on the 540-day rule.

## 3. Board movements, top 15

Against **main after PR #3** (the effect of this branch's config only):

| Division | Fighter | Move | Cause |
|---|---|---|---|
| Bantamweight | Farid Basharat | 15 -> out | Exclusion (carried). Barcelos 16 -> 15 |
| Featherweight | Cub Swanson | 12 -> out | Exclusion (carried). Riley, Santos, McMillen, Mariscal up one |
| Featherweight | Zalal / Arnold Allen | 9 -> 8 / 8 -> 9 | Division rescaling after exclusions |
| Flyweight | Allan Nascimento | 10 -> out | Exclusion (carried). Elliott, Ulanbekov, I. Rodriguez, Lima, Hasan up one, Temirov 16 -> 15 |
| Heavyweight | Faglier / Leka | 16 -> 15 / 15 -> 16 | Faglier's short-notice win (carried) |
| Welterweight | Mike Malott | 10 -> 9 | Rescaling |
| Welterweight | Jacobe Smith | 11 -> 10 | Short-notice win weighted 1.2x (item 3) |
| Welterweight | Kamaru Usman | 9 -> 11 | Passed by both |
| Women's Bantamweight | Ketlen Vieira | 5 -> out | Exclusion (carried). Cavalcanti through Chandler each up one, Cornolle 17 -> 15 |

Against **current main** (through UFC 333), the Vegas 123 results also show:

| Division | Fighter | Move | Cause |
|---|---|---|---|
| Lightweight | Tom Nolan | 26 -> 14 | R3 KO of Moicano (now 5-0, W6) |
| Lightweight | Renato Moicano | 6 -> 16 | Same bout. Last five now 2-3 |
| Lightweight | Saint Denis through Fiziev | each up one | Behind Moicano's drop |
| Women's Bantamweight | Luana Santos | 6 -> 4 | UD over Yana Santos (plus the Vieira exclusion) |
| Women's Flyweight | Lucia Szabova | out -> 14 | UFC debut, R3 TKO of Tainara Lisboa |
| Women's Strawweight | Piera Rodriguez | 16 -> 13 | UD over Talita Alencar |
| Flyweight | Albazi / Elliott | 10 -> 9 / 9 -> 10 | Knock-on |

Champions are unchanged in every division.

## 4. Audit trail items that look wrong or need judgment

1. **Lucia Szabova at WFLW #14 after one UFC fight.** Her score is 0.043 with a ledger of zero. This reflects thin depth at women's flyweight, not her résumé. The rules work as written, but expect questions.
2. **Jacobe Smith at WW #10 with no top-15 wins** (0 quality wins, ledger +0.2). He sits on a 5-0 run, and the short-notice multiplier lifts him above Usman. This is correct under v1.0, but it is the kind of placement the product endpoint should log.
3. **Tom Nolan dropped from score order #13 to #14 by the head-to-head rule.** He sits two places above Moicano, whom he just knocked out, so the result is consistent.

## 5. Forward validation (outputs/forward_validation.json, prospective since the Oct 1 freeze)

| Primary population (both scored) | Value |
|---|---|
| Bouts | 37 |
| REAL concordance | 54.1% (95% CI 38.4% to 69.0%) |
| REAL log loss | 0.724 |
| Results-only Elo log loss | 0.721 |
| Performance-adjusted Elo log loss | 0.759 |

Both fighters in the top 15: 9 bouts, 77.8%. Title fights: 3 of 3. Where both fighters held an official rank (12 bouts), the official board was concordant in 50%, REAL in 66.7%. These numbers are interim and descriptive only (PREREGISTRATION section 2).

## 6. Picks record (outputs/picks_summary.json)

- **Graded 49: 27 correct, 22 incorrect (55.1%, Wilson 95% 41.3% to 68.1%).** Log loss is 0.700, against 0.693 for a coin flip.
- **UFC Vegas 123: 9 of 11 correct.** The misses were Moicano over Nolan and Berggren over Sezinando. There was one no-pick, Marshall vs. Hope: the probability fell inside the no-pick band at lock time.
- Same bouts: results-only Elo 49.0%, shadow v1.1 57.1%. Market at lock (22 bouts with odds): 77.3% (0.597 log loss), against the model's 68.2% (0.647) on those bouts.
- **Pending 44.**
- **Void 3:**
  - Kareckaite vs. Gatto (Oct 10): draw or no contest.
  - Horth vs. Cerminara and Mahjoub vs. Sutherland (Oct 17): the bouts fell through.
- **Coming voids:**
  - Allen vs. Pico (UFC 333): Keita replaced Allen. It voids at the 10-day rule on Nov 3.
  - Three stale Vegas 123 locks (Brown vs. Leal, Marshall vs. Bolanos, Bekoev vs. Petroski): the bouts changed, and they void about Nov 10.
  - Bonfim vs. Brady (Nov 7): Brady withdrew.
