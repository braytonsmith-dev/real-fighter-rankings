# Weekly review proposal, 2026-10-05

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged; weights and rules are unchanged (method v1.0 frozen). Merging this branch approves every change below; to reject one, revert that file before merging.

Events covered since the last board (data through 2026-09-26): **UFC 332: Silva vs. Wang** (Oct 3, 2026). The Sept 26 Fight Night (Rosas Jr. vs. Barcelos) was already in the data on main and was re-checked for short-notice bouts. Raw UFCStats CSVs were refreshed from Greco1899/scrape_ufc_stats; the board now runs through 2026-10-03.

## 1. Proposed changes

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 1 | `config/champions_override.yaml` | Remove `Women's Flyweight: VACANT` | Natalia Silva won the vacant title over Wang Cong at UFC 332 (UD 48-47, 48-47, 49-46). With the override left in, the board showed the title vacant and Silva as contender #3. The title bout is now in the data, so no override is needed. | https://sports.yahoo.com/articles/ufc-332-results-full-card-114845804.html |
| 2 | `config/champions_override.yaml` | `Heavyweight: VACANT` -> `Heavyweight: Ciryl Gane` | Gane was promoted from interim to undisputed champion after Aspinall vacated. Dana White confirmed it at the UFC 331 press conference (Sept 20), and UFC 334 (Nov 14) bills Gane (c) vs. Josh Hokit for the title. ufc.com/rankings lists Gane as Champion. | https://khelnow.com/ufc/has-ciryl-gane-been-promoted-to-heavyweight-champion-ahead-of-ufc-334-202609 ; https://www.ufc.com/rankings |
| 3 | `config/interim_champions.yaml` | Remove `Heavyweight: Ciryl Gane` (file now `{}`) | Follows from change 2: Gane no longer holds an interim title. | same as 2 |
| 4 | `config/roster_exclusions.yaml` | Add Court McGee | He confirmed his retirement after his R3 KO loss to Eric Nolan at UFC 332. No board effect, because he was not on a top-30 board. | https://www.si.com/fannation/mma/news/25-fight-ufc-veteran-confirms-retirement-after-knockout-loss-at-ufc-332 |
| 5 | `config/short_notice.yaml` | Luis Hernandez, 2026-09-26 (win) | Replaced Mickey Gall against Sedriques Dumas with about 2 days' notice, in his UFC debut. | https://sports.yahoo.com/articles/sedriques-dumas-gets-opponent-ufc-214451163.html |
| 6 | `config/short_notice.yaml` | Anthony Romero, 2026-10-03 (loss) | Replaced Bernardo Sopaj against Marcus McGhee with 3 days' notice, in his UFC debut. The config key is name plus date, so the second "Anthony Romero" on UFCStats is not affected. | https://www.ufc.com/news/updates-to-ufc-332-silva-vs-wang |
| 7 | `config/short_notice.yaml` | Bruce Whitehead, 2026-10-03 (loss) | His bout with Jacobe Smith was added Sept 24, giving him 9 days' notice, in his UFC debut. | https://boxingnews.com/news/jacobe-smith-ufc-332-nine-days-notice/ |
| 8 | `data/external/ufc_media.csv` | Gane row: `is_champion 1, is_interim 0` | ufc.com still shows "Last updated: Sep. 26", so every rank in the file matched the live page and nothing else changed. `ufc_meta.csv` was left as is: it is the same Sept 26 release, and I did not separately verify the Meta block's champion label. | https://www.ufc.com/rankings |
| 9 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*` | Refreshed UFCStats data and rebuilt with `run_all --quick` | Adds UFC 332. Upstream also replaced the Rosas Jr. vs. Barcelos round stats. That bout was a finish, so no rating moved. | Greco1899/scrape_ufc_stats |

## 2. Needs Brayton's judgment (not applied)

- **Rafael dos Anjos retirement.** He left his gloves in the cage after his R2 TKO loss to Alexander Hernandez at UFC 332, but I found no formal announcement (https://www.mmanews.com/article/dos-anjos-retires-loss-hernandez). He sits at Lightweight #80, so adding him to `roster_exclusions.yaml` would not change any visible board.
- **Jacobe Smith short notice.** He also faced Whitehead on 9 days' notice after his planned fight with Kevin Holland fell through. I counted only the debutant who accepted the late add. If you count Smith too, his win goes from 1x to 1.2x; he is already up 20 -> 13.
- **Tom Aspinall reserved spot.** He is still shown as R (reserved) at Heavyweight. Gane is now the full champion and no title shot has been publicly promised to Aspinall on his return. The entry is still consistent with the stated rule ("vacated because of injury"), so I kept it.
- **Valentina Shevchenko reserved spot.** Kept. She said "keep my belt warm," but no title shot is official.
- **Snapshot handling (code, not config).** `official_ranks.py` reads only the latest `ufc_media.csv` snapshot after June 16, 2026. When ufc.com updates (likely Tuesday), overwriting the file will drop the Sept 26 snapshot, and UFC 332 bouts will fall back to the June 16 ranks. Before the next refresh, consider keeping dated snapshots, for example as appended rows that `compare.py` filters to the latest `as_of`. I did not change this, since it is a code change.

## 3. Board movements, top 15 (main -> this branch)

Only fighters who were or are in a top 15 and changed position are listed. Most of the movement follows from UFC 332 results; the Women's Flyweight shift follows from change 1.

| Division | Fighter | Main | Branch | Cause |
|---|---|---|---|---|
| Heavyweight | Ciryl Gane | IC | C | change 2 |
| Heavyweight | Anthony Wint | 15 | 13 | 23-second KO of Lucas Armand |
| Women's Flyweight | Natalia Silva | 3 | C | won the vacant title (change 1) |
| Women's Flyweight | Namajunas, Blanchfield, Barber, Jasudavicius, O'Neill, Wang Cong, Judice, Maverick, Barbosa, Tarin, Cortez, Aldrich, Horth | 4-16 | 3-15 | each moves up one as Silva leaves the numbered board; Wang Cong 9 -> 8 after the title loss |
| Bantamweight | Payton Talbott | 14 | 9 | R1 KO of Figueiredo (#9 official) |
| Bantamweight | Marcus McGhee | 11 | 8 | R1 TKO of Anthony Romero |
| Bantamweight | Montel Jackson | 9 | 7 | no bout; Barcelos's head-to-head lift over him no longer applies |
| Bantamweight | Raul Rosas Jr. | 7 | 10 | no bout; see section 4 |
| Bantamweight | Raoni Barcelos | 8 | 16 | no bout; see section 4 |
| Bantamweight | David Martinez, Zahabi, Basharat | 10, 15, 16 | 11, 14, 15 | knock-on |
| Lightweight | King Green | 9 | 17 | R1 KO loss to Esteban Ribovics |
| Lightweight | Dawson, Gamrot, Miller, Padilla, Ruffy, Fiziev, Turner | 10-16 | 9-15 | each up one |
| Middleweight | Ateba Gautier | 12 | 25 | R1 TKO loss to Roman Kopylov |
| Middleweight | Aliskerov, Page, Nickal, Rowston | 13-16 | 12-15 | each up one |
| Welterweight | Jacobe Smith | 20 | 13 | R1 TKO of Bruce Whitehead (4-0) |
| Welterweight | Malott, Amosov, Magny | 13-15 | 14-16 | knock-on |
| Flyweight | Imanol Rodriguez | 18 | 13 | R1 body-kick KO of Alden Coria |
| Flyweight | Alden Coria | 13 | 22 | same bout |
| Women's Strawweight | Tatiana Suarez / Virna Jandiroba | 3 / 2 | 2 / 3 | no bouts; see section 4 |
| Women's Strawweight | Iasmin Lucindo | 5 | 7 | 421 days inactive, so the inactivity penalty is growing |
| Women's Strawweight | Kline, Gomes, Amorim, Andrade, Yan Xiaonan, Piera Rodriguez | | | 1-3 place knock-on shifts |
| Women's Bantamweight | Bia Mesquita / Julianna Pena | 9 / 8 | 8 / 9 | no bouts; small score shift |

Brayton's favorites: no favorite on the top-ten list fought this week, and none of their board positions changed.

## 4. Audit-trail items that look wrong

1. **Head-to-head chains move fighters who did not fight.** On main, Raoni Barcelos sat at Bantamweight #8 (score order #16): the chain lifted him above Talbott and then Montel Jackson, even though Rosas Jr. had just knocked him out. This week Talbott jumped to #9, the chain no longer reaches, and Barcelos falls back to #16. Rosas Jr., who won that main event, drops 7 -> 10 because his lift depended on standing directly above Barcelos. The rule follows its spec, but one fighter moving 8 places in each of two weeks without fighting is an instability worth a look for v1.1. Rule ideas: a cap on chained lifts, or apply head-to-head in a single pass.
2. **Rescaling swaps places with no bouts.** Women's Strawweight #2 and #3 (Jandiroba and Suarez) traded places only because Diana Belbita and Istela Nunes aged out of the active window. That raised the division's 10th-percentile rating from 1390 to 1433, which changed the interdecile scale and so the balance between rating and ledger. The effect is small, but it is a rank change caused by fighters at the bottom of the division.
3. **Heavyweight #2 Josh Hokit (score order #6).** He reaches #2 via head-to-head and then the title cycle (Pereira at #4). His score (0.54) is well below Blaydes (0.83) and Volkov (1.13). This is defensible because he has the booked title shot, but he leans entirely on rules.
4. **Flyweight #3 Brandon Royval (score order #6).** He is lifted three places because Pantoja, Taira and Moreno are held at #4-#6 by the title-cycle rule. That works as designed; I note it because Royval is on the favorites list.

## 5. Forward validation (`outputs/forward_validation.json`)

The first prospective bouts since the v1.0 freeze on Oct 1 are from UFC 332. The sample is far too small to read anything into.

| Block | Bouts | REAL concordance (Wilson 95%) | REAL log loss | Official board, same bouts |
|---|---|---|---|---|
| Primary: both fighters scored | 8 | 62.5% (30.6% to 86.3%) | 0.6115 | 2 both ranked: official 50%, REAL 100% |
| Both in top 30 | 3 | 33.3% (6.1% to 79.2%) | 0.7204 | 1 bout: both correct |
| Both in top 15 | 1 | 100% | 0.4373 | 1 bout: both correct |
| Title fights | 1 | 100% (Silva over Wang) | 0.4373 | correct |

Retrospective reconstruction (128 snapshots, in-sample): 942 bouts, 61.5% concordance (58.3% to 64.5%), log loss 0.6669, against 0.6726 for results-only Elo and 0.6498 for performance-adjusted Elo. These figures are unchanged from main.

## 6. Merge note

The `weekly-boards` GitHub Action rebuilds main every Monday at 13:00 UTC and commits refreshed data and outputs. If it has run, generated files under `data/`, `outputs/` and `docs/` will conflict. The config files will not. To resolve: take this branch's `config/` and `data/external/ufc_media.csv`, then re-run `PYTHONPATH=src python3 -m mmalab.run_all --quick` on the merge.
