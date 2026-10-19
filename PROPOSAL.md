# Weekly review proposal, 2026-10-19

Prepared by the scheduled weekly review for Brayton's approval. Nothing here is merged. Weights, rules, thresholds and `config/weights.yaml` are unchanged (SHA-256 still `ea1a823c...5cc2`, matching the v1.0 freeze). Merging this branch approves every change below; to reject one, revert that line before merging.

Events covered: **UFC Fight Night: Buckley vs. Malott** (Edmonton, Oct 17, 2026), the only event since main's data (through UFC Vegas 122, Oct 10). Raw UFCStats CSVs were refreshed from Greco1899/scrape_ufc_stats; the board now runs through 2026-10-17. Next card: UFC 333, Oct 24 (Abu Dhabi).

## 1. Proposed changes

### A. This week

| # | File | Change | Why | Source |
|---|---|---|---|---|
| 1 | `config/roster_exclusions.yaml` | Add Farid Basharat | Contract expired after UFC 329 and was not renewed; he confirmed the departure Oct 15 | https://cagesidepress.com/2026/10/15/undefeated-farid-basharat-confirms-ufc-departure/ |
| 2 | `config/roster_exclusions.yaml` | Add Ismael Bonfim | Released Oct 12 after missing weight by 7.5 lb and losing at UFC Vegas 122 (4th straight loss) | https://heavy.com/sports/ufc/ismael-bonfim-released-from-ufc-roster/ |
| 3 | `config/short_notice.yaml` | Joel Faglier, 2026-10-17 (win) | Replaced Louie Sutherland vs Javad Mahjoub, reported Sept 30, about 17 days out | https://bvmsports.com/2026/09/30/faglier-to-replace-sutherland-at-ufc-edmonton/ ; ufc.com fight-by-fight preview |
| 4 | `config/short_notice.yaml` | Mackenzie Stiller, 2026-10-17 (loss) | Replaced injured Jamey-Lyn Horth vs Katlyn Cerminara, reported Oct 1, 16 days out | https://www.si.com/fannation/mma/news/ex-ufc-title-challenger-gets-new-opponent-just-weeks-out-from-ufc-edmonton |
| 5 | `config/short_notice.yaml` | Nick Galanti, 2026-10-17 (win) | Replaced Gilbert Urbina vs Julien Leblanc; "I got 15 days to lose 35 pounds" | https://middleeasy.com/mma-news/nick-galanti-short-notice-weight-cut-ufc-edmonton-debut ; ufc.com preview |
| 6 | `data/raw/*`, `data/processed/*`, `outputs/*`, `docs/*`, `METHODOLOGY.md`, `predictions/picks.csv` | Refreshed UFCStats and rebuilt with `run_all --quick` | Adds Edmonton; grades its picks; adds `outputs/history/board_2026-10-17.csv` | Greco1899/scrape_ufc_stats |

### B. Backlog: 2026 departures that were never entered (32 fighters)

While checking this week's cuts, the review found that the exclusions file holds almost none of the 2026 roster departures. These fighters are still being scored, and several sit in a top 30. Each line below is now in `config/roster_exclusions.yaml` with its source URL; each was checked against the fight data to confirm no UFC bout after the departure date.

| Fighter (board position on main) | Departure | Source |
|---|---|---|
| Ketlen Vieira (W-BW #4) | removed May 2026 | mmafighting.com/ufc/489870 |
| Allan Nascimento (FLY #11) | passed away Aug 3, 2026 | ufc.com/news/remembering-allan-nascimento-1991-2026 ; cagesidepress.com |
| Cub Swanson (FW #12) | retired Apr 11 | cagesidepress.com |
| Daniel Marcos (BW #20) | not re-signed, May 29 | heavy.com |
| Hailey Cowan (W-BW #25) | retired Aug 2026 | cagesidepress.com |
| Mayra Bueno Silva (W-BW #26) | removed May 18 | heavy.com |
| Eryk Anders, Matt Schnell, Javid Basharat, Alex Morono, Felipe Bunes, Jose Daniel Medina, Phil Rowe, Patchy Mix, Gilbert Burns, Austen Lane, Themba Gorimbo, Max Griffin, Andreas Gustafsson, Nathan Fletcher, Cameron Smotherman, Ariane Carnelossi, Thiago Moises, Carlston Harris, Trey Waters, Michel Pereira, Stewart Nicoll, Darren Elkins, Cody Gibson, Bekzat Almakhan, Edson Barboza, Ravena Oliveira (all outside the top 30) | Jan to Aug 2026 | see each line in the file |

These are facts, not method, so PREREGISTRATION.md section 1 allows them. They change only snapshots from Oct 17 on; the Oct 10 snapshot that feeds this week's forward-validation rows was not touched.

## 2. Board movements, top 15 (main -> this branch)

| Division | Fighter | Move | Cause |
|---|---|---|---|
| Welterweight | Mike Malott | 14 -> 9 | R2 KO of Buckley |
| Welterweight | Joaquin Buckley | 9 -> 24 | KO loss, third straight loss (last five 2-3) |
| Women's Flyweight | Jasmine Jasudavicius | 6 -> 4 | UD over Blanchfield (head-to-head rule) |
| Women's Flyweight | Erin Blanchfield | 4 -> 5 | Same bout |
| Women's Flyweight | Katlyn Cerminara | new -> 7 | R1 TKO of Stiller |
| Women's Bantamweight | Chelsea Chandler | 20 -> 14 | R1 kimura over Croden |
| Women's Bantamweight | Melissa Croden | 14 -> 16 | Same bout |
| Heavyweight | Joel Faglier | new -> 15 | Debut TKO win (short notice) |
| Women's Bantamweight | Ketlen Vieira | 4 -> out | Exclusion; #5 to #15 each move up one or two |
| Flyweight | Allan Nascimento | 11 -> out | Exclusion; #12 to #16 each move up one |
| Featherweight | Cub Swanson | 12 -> out | Exclusion; #13 to #16 each move up one |
| Bantamweight | Farid Basharat | 15 -> out | Exclusion; Raoni Barcelos 16 -> 15 |
| Flyweight | Asu Almabayev / Brandon Royval | 7 -> 3 / 3 -> 7 | Neither fought; see section 3 |
| Featherweight | Youssef Zalal / Arnold Allen | 9 -> 8 / 8 -> 9 | Neither fought; scores 0.495 vs 0.490 after rescaling |
| Welterweight | Jacobe Smith / Rinat Fakhretdinov | 13 -> 12 / 12 -> 13 | Neither fought; scores 0.304 vs 0.301 |

## 3. Audit trail items that look wrong or need judgment

1. **Flyweight #3/#7 swap with no bout.** Royval (0.387) and Almabayev (0.390) are 0.003 apart. Removing departed fighters moved the division's scaling just enough to flip them at #6/#7, and the title-cycle rule then lifts whoever is #6 to #3. One fighter moves four places on a rounding-level change. This is a pre-registered product endpoint ("moves of more than three places without a new bout"), so it should be logged, not fixed, under v1.0. It is a candidate for v1.1.
2. **Departures held back because no approved outlet confirmed them.** Tecia Pennington (W-SW #14; only bjpenn.com reports she "parts ways"), Ivan Erslan, Tuco Tokkos and Daniel Barez (only GIDStats), Lucas Almeida (only AgentMMA), Luana Carolina (W-FLY #20), Bruna Brasil and Antonio Trocoli (only HITC), Mohammed Usman (30-month suspension, but removal not confirmed), Rafael Cerqueira, Mohammad Yahya, Daniel Frunza, Aoriqileng, Adam Fugitt. Darrius Flowers was reported released Jan 28 but fought in the UFC on Apr 4, so he was left in. Your call on each.
3. **Fought after a reported release, left in:** Sedriques Dumas, Gianni Vazquez, Jessie Rosas Jr.
4. **Arnold Allen** withdrew from UFC 333 with an injury (lowkickmma.com, Sept 18). His last bout was May 16, 2026, so no layoff entry is needed yet.

## 4. Not done this week

- **ufc.com/rankings could not be fetched** (the fetch needed a permission approval that no one was there to give), so `data/external/ufc_media.csv` and `ufc_meta.csv` were not refreshed. The Oct 3 release is still the latest stored. Edmonton opponents' official ranks therefore come from that release.
- **ESPN schedule feed was unreachable**, so no new picks were locked and `predictions/unmatched_names.csv` was not regenerated. The listed names (Pérez, Faglier, Stiller, Galanti, Jourdain, Chovancek, Mahjoub) all now exist in UFCStats. Chopurov, Szabova and Kropschot already have UFCStats pages. No aliases are needed.
- No title changes, interim titles, new reserved spots, division moves, returns from layoff, or overturned results were found for the period.

## 5. Forward validation (outputs/forward_validation.json, prospective since Oct 1 freeze)

| Primary population | Main (14 bouts) | This branch (19 bouts) |
|---|---|---|
| REAL concordance | 57.1% | 47.4% (95% CI 27.3% to 68.3%) |
| REAL log loss | 0.701 | 0.766 |
| Results-only Elo log loss | 0.742 | 0.774 |
| Performance-adjusted Elo log loss | 0.821 | 0.847 |

Interim and descriptive only (PREREGISTRATION.md section 2). Edmonton added five bouts; the higher-placed fighter lost four of them (Blanchfield, Buckley, Croden, Daukaus).

## 6. Picks record (outputs/picks_summary.json)

- Graded 24: 9 correct, 15 incorrect (37.5%, Wilson 95% 21.2% to 57.3%); log loss 0.763 against 0.693 for a coin flip.
- Edmonton: 5 of 13 correct (log loss 0.766). Results-only Elo on the same 24 bouts: 37.5%, 0.737. Shadow v1.1: 45.8%, 0.806.
- Pending 25. Two Edmonton picks will void on Oct 27 because the bouts never happened: Horth vs Cerminara and Mahjoub vs Sutherland (both replaced; their replacements were graded).
- Void 1: Kareckaite vs Gatto (Oct 10), draw or no contest, not scored.
