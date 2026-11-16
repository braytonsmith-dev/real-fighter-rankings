# Weekly review proposal, 2026-11-09

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged. Weights, rules, thresholds and `config/weights.yaml` are unchanged (frozen v1.0, SHA-256 still `ea1a823c...5cc2`). Merging this branch approves every change below. To reject one, revert that line before merging.

Events covered: **UFC Fight Night: Cortes Acosta vs. Walker** (UFC Vegas 124, Nov 7, 2026), the only event since last week's review. Raw UFCStats CSVs and the martj42 rankings history (now through Nov 3) were refreshed. The board now runs through 2026-11-07. Next card: UFC 334, Nov 14 (Gane vs. Hokit, Harrison vs. Nunes).

**Branch lineage.** Built on current main (`57d2c9e`, which includes the merged 2026-11-02 review). No older review branches are outstanding. `mmalab.checks --ref origin/main` passes and `pytest tests` passes (245 passed, 1 xfailed).

**Snapshot note.** This branch adds `outputs/history/board_2026-11-07.csv` (and the v1.1 twin), built with the config below. It is the pre-event snapshot for UFC 334 under PREREGISTRATION section 3, so it should be merged before Nov 14. If the Monday workflow commits its own `board_2026-11-07.csv` to main first, keep this branch's version when resolving the conflict (the only difference is the three short-notice entries).

## 1. Proposed changes

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 1 | `config/short_notice.yaml` | Waldo Cortes Acosta, 2026-11-07 (L) | New main event after Sean Brady withdrew (staph infection) from Bonfim vs. Brady. Reported Oct 29, 9 days notice. Neither man was booked on the card before. | https://cagesidepress.com/2026/10/29/ufc-vegas-124-loses-bonfim-vs-brady-heavyweight-headliner/ ; https://heavy.com/sports/ufc/ufc-vegas-124-gets-brand-new-heavyweight-headliner/ |
| 2 | `config/short_notice.yaml` | Johnny Walker, 2026-11-07 (W) | Same bout, 9 days notice. Won by R3 KO. | Same as item 1 ; https://mmasucka.com/news/waldo-cortes-acosta-vs-johnny-walker-set-as-new-ufc-vegas-124-main-event-after-sean-brady-withdraws/ |
| 3 | `config/short_notice.yaml` | Carlos Calderon, 2026-11-07 (L) | Replaced Lucas Brennan (torn ACL) vs. Austin Bashi. Reported Nov 4, 4 days notice. Lost by R1 submission. | https://boxingnews.com/news/calderon-ufc-vegas-124-short-notice/ |
| 4 | `config/name_aliases.yaml` | `jose henrique: jose souza` | ESPN listed "Jose Henrique" (event 401928118, Henrique vs. Parsons). UFCStats records the same bout as Jonny Parsons vs. **Jose Souza** (fighter-details/20a0e4cc5227c117, who also beat Ding Meng). Full name Jose Henrique Souza. Last week's note that he looked like a debutant was wrong. | https://www.rotowire.com/mma/player/jose-henrique-souza-2744 ; https://www.thestatszone.com/ufc-fight-night-jonny-parsons-vs-jose-henrique-souza-preview-prediction-234641 |
| 5 | `data/external/ufc_media.csv`, `ufc_meta.csv` | Appended the ufc.com release labeled "Last updated: Saturday, Oct. 31" (as_of 2026-10-31, 176 rows each) | It already reflects Vegas 123 (Nolan up to media #13 and Meta #7, Luana Santos up). Ranks are read strictly before the fight date, so these rows serve Vegas 124 onward. Gane is stored as champion, not interim, as in prior weeks: only the image alt text says interim. The media panel has three ties, each stored as two rows: WW #9 Malott and Usman, HW #12 Lewis and Fortune, WBW #5 L. Santos and Pennington. Muhammad Saidov left the media LHW list, and Yakhyaev entered at #12. | https://www.ufc.com/rankings |
| 6 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*`, `METHODOLOGY.md`, `predictions/picks.csv` (grades only) | Rebuilt with `run_all --quick` | Adds Vegas 124 and grades its picks. No new locks: the ESPN feed was unreachable from this run, so the saved copy was used. | Greco1899/scrape_ufc_stats, martj42/ufc_rankings_history |

Item 4 cannot regrade the locked Parsons vs. "Jose Henrique" row, because rows are never edited and grading uses the names matched at lock time. That pick (Parsons, who lost by R1 KO) will void on Nov 17 under the 10-day rule. The alias fixes his future locks only.

### Checked, nothing to add

- **Other Vegas 124 bouts:** Suarez vs. Jandiroba, Grant vs. Smith, Elekana vs. Fernando, Cachoeira vs. Milosevic, Raposo vs. Degli (booked Oct 1, not Nov 2 as I noted last week), Silva vs. Fernandes, Delano vs. Magomedov, Ko vs. Turman and Parsons vs. Souza were all booked by Sep 29 or Oct 1. There were no weight misses. Bashi only changed opponents, so he has no entry.
- **Retirements and releases:** none took effect this week. Davey Grant said he will keep fighting (https://sports.yahoo.com/articles/gutted-davey-grant-issues-statement-144030427.html). Stephen Thompson confirmed that UFC 334 vs. Radtke is his last fight (https://heavy.com/sports/ufc/stephen-thompson-confirms-retirement-ufc-334/). His entry belongs in next week's review, dated Nov 15.
- **Injuries and returns:** Kayla Harrison is confirmed for UFC 334 vs. Amanda Nunes. Her layoff entry closes after that bout (next week). Sean Brady (staph infection, no timeline) is at about 190 days and needs no entry yet. Aspinall and Shevchenko are unchanged.
- **Titles:** unchanged. Prates vs. Morales for the interim WW title is still set for UFC 336, so no entry is needed until it happens.
- **Division moves:** none confirmed. Makhachev only said a middleweight move is being discussed (https://bloodyelbow.com/2026/11/07/islam-makhachev-confirms-his-team-is-discussing-a-move-to-the-ufc-middleweight-division/). Johnny Walker moved to HW on his own: his last two bouts are there, so the weight-band rule placed him without an override.
- **Drug-test overturns:** none. Jaqueline Amorim received a six-month CSAD suspension for contamination, and no result was overturned (https://www.ufc.com/news/statement-on-jaqueline-amorim).
- **Unmatched names:** Calderon, Degli and Lorenço now match. Samuel Sanches (UFC 334) has a UFCStats page.

## 2. Needs Brayton's judgment

1. **Two more possible short-notice entries, sourced only by aggregators.** I did not add them.
   - **Thomas Petersen** replaced Alvin Hines vs. Gabriel Lorenço. agentmma dates it Oct 25, which is 13 days. Petersen won by R3 KO. mmasucka says only "late October", and one agentmma headline reverses who replaced whom.
   - **Andre Petroski** moved from Vegas 123 after Bekoev withdrew. He was paired Oct 23 with Mantas Kondratavicius, whose opponent Wes Schultz had dropped out. That is 15 days. Petroski won by R2 KO. Sources: agentmma and ufcalendar only.
   - If you accept either, I will add it next week. Kondratavicius was already booked on the card, so like Bashi he gets no entry.
2. **Grant Dawson.** roster.watch tags him "OUT" with no date or reason. I found no reputable confirmation, so there is no exclusion. He is Meta LW #11.
3. **McGregor's "my last fight" post (Nov 1).** He means the last fight on his contract, not a retirement, so there is no entry.
4. **Still open:** Naimov, Buzukja, Pennington and the other single-source departures, plus Pena's inactivity clock. **Jose Aldo resolved itself.** He reached 540 days without a documented injury and left the BW board (#13 -> out).

## 3. Board movements, top 15 (versus main, data through Oct 31)

The three short-notice entries change scores slightly but move no one. For example, Walker goes from 0.575 to 0.587 and Cortes Acosta from 0.458 to 0.501. Every move below comes from the Vegas 124 results and the calendar.

| Division | Fighter | Move | Cause |
|---|---|---|---|
| Heavyweight | Johnny Walker | LHW #12 -> HW #6 | R3 KO of Cortes Acosta. His last two bouts are at HW, so the board follows them. Score order #5, then head-to-head -> #6. |
| Heavyweight | Waldo Cortes Acosta | 5 -> 7 | Same bout. Last five now 2-3 (L3). |
| Heavyweight | Pavlovich / D. Lewis | 6 -> 5 / 9 -> 8 | Knock-on |
| Heavyweight | V. Walker, Pinto, Pericic, Kuniev, Petrino, Wint, Saricam | each down one or two | Walker's entry. Faglier 15 -> 16. |
| Light Heavyweight | Menifield, Baraniewski, Saidov | 13/14/15 -> 12/13/14 | Walker left the division |
| Light Heavyweight | Lucas Fernando / Billy Elekana | 17 -> 15 / 16 -> 24 | Fernando's UD over Elekana |
| Bantamweight | Elijah Smith | 18 -> 13 | 60-second KO of Davey Grant (4-0, W4). Grant 20 -> out of the top 30. |
| Bantamweight | Jose Aldo | 13 -> out | 540-day inactivity limit, no injury entry |
| Middleweight | Abus Magomedov | 17 -> 12 (no bout) | His Nov 4, 2023 loss to Borralho passed the three-year loss horizon (`decisive_loss_years: 3`). Aliskerov, Page and Nickal each down one. Susurkaev 15 -> 16. |
| Welterweight | Rinat Fakhretdinov | 13 -> 15 | Inactivity penalty (428 days). Amosov 14 -> 13, Magny 15 -> 14. |
| Women's Bantamweight | Nina Milosevic | 13 -> 10 | R2 KO of Cachoeira. Pereira, Montague and Rosa each down one. Croden 16 -> 15. |
| Women's Strawweight | Denise Gomes | 8 -> 6 (no bout) | Her Nov 4, 2023 loss to Angela Hill passed the same three-year horizon. Godinez and Kline each down one. |
| Women's Strawweight | Suarez / Jandiroba | 2 / 3, unchanged | Suarez's UD confirms the existing order |

Champions are unchanged in every division.

## 4. Audit trail items that look wrong or need judgment

1. **Abus Magomedov (+5) and Denise Gomes (+2) moved without fighting.** Both are caused by the same Nov 4, 2023 card aging out of the three-year loss window. The rule works as written. Abus's move counts toward the product endpoint "moves of more than three places without a new bout", so it is worth a line in any write-up.
2. **Elijah Smith at BW #13 with zero top-15 wins** (ledger +0.2, a 4-0 run). This is the same pattern as Jacobe Smith last week: correct under v1.0, but thin.
3. **Johnny Walker at HW #6 with a 3-2 last five.** His ledger is strong (3 top-10 wins, entrenched). The head-to-head rule drops him one place (score order #5 -> #6). I see nothing wrong.
4. **Tyrell Fortune fell out of the HW top 30** (24 -> score order #33). Last week only a head-to-head lift held him at #24. Walker's arrival pushed him to score order #33, beyond the lift's reach (`max_gap_recent: 6`). He is media panel HW #12 (tied), so the comparison page will flag him.

## 5. Forward validation (outputs/forward_validation.json, prospective since the Oct 1 freeze)

| Primary population (both scored) | Value |
|---|---|
| Bouts | 45 |
| REAL concordance | 55.6% (95% CI 41.2% to 69.1%) |
| REAL log loss | 0.716 |
| Results-only Elo log loss | 0.716 |
| Performance-adjusted Elo log loss | 0.744 |

Secondary populations:

| Population | Bouts | REAL concordance |
|---|---|---|
| Both fighters in the top 30 | 24 | 66.7% |
| Both in the top 15 | 10 | 80.0% |
| Title fights | 3 | 3 of 3 |

Where both fighters held an official rank (14 bouts), the official board was concordant in 57.1% and REAL in 71.4%. These numbers are interim and descriptive only (PREREGISTRATION section 2).

## 6. Picks record (outputs/picks_summary.json)

- **Graded 61: 34 correct, 27 incorrect (55.7%, Wilson 95% 43.3% to 67.5%).** Log loss is 0.686, against 0.693 for a coin flip.
- **UFC Vegas 124: 7 of 12 correct.** One no-pick: the Cortes Acosta vs. Walker main event fell inside the two-point band at lock. The misses:
  - Nakamura over Schmid
  - Grant over Smith
  - Jandiroba over Suarez
  - Degli over Raposo
  - Kondratavicius over Petroski
- Same bouts: results-only Elo 50.8%, shadow v1.1 59.0% (log loss 0.683). Market at lock (32 bouts with odds): 75.0% (0.613 log loss), against the model's 62.5% (0.652) on those bouts.
- **Pending 31. No-pick 2.**
- **Void 4:**
  - Kareckaite vs. Gatto: draw or no contest.
  - Horth vs. Cerminara: the bout fell through.
  - Mahjoub vs. Sutherland: the bout fell through.
  - Allen vs. Pico: Keita replaced Allen. It voided at the 10-day rule on Nov 3.
- **Coming voids:**
  - Nov 10 (three Vegas 123 locks whose bouts changed):
    - Brown vs. Leal
    - Marshall vs. Bolanos
    - Bekoev vs. Petroski
  - Nov 17 (five Vegas 124 locks):
    - Bonfim vs. Brady: Brady withdrew.
    - Bashi vs. Brennan: Calderon replaced Brennan.
    - Lorenço vs. Hines: Petersen replaced Hines.
    - Kondratavicius vs. Schultz: Petroski replaced Schultz.
    - Parsons vs. "Jose Henrique": a name mismatch (item 4). Parsons lost, so this void hides a miss.
