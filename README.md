# REAL Fighter Rankings

Results, Evidence, Analytics, Ledger. Open, reproducible UFC rankings built from public data: a weekly resume board (who has earned it), a separately graded prediction model (who would be favored), and a card-quality index for matchmaking research. Companion to the SSAC27 abstract in `paper/abstract_ssac27.md`.

- Site: https://braytonsmith-dev.github.io/real-fighter-rankings/ (boards, side-by-side with public boards, prediction model, methodology)
- Methodology, version 1.0, with every rule, weight, and worked example: [METHODOLOGY.md](METHODOLOGY.md) (regenerated on every rebuild from `config/weights.yaml` and the audit trail)
- Per-fighter audit trail: `outputs/audit_top30.csv`; forward validation: `outputs/forward_validation.json`

Principle: a fighter is ranked on how he performed against the fighters he faced, and how good those fighters were.

## What it produces

| Output | File |
|---|---|
| Divisional boards, champion plus top 30, movement since the last event | `outputs/composite_boards.md`, `docs/index.html` |
| Audit trail: score order, rule moves, ledger detail for every contender | `outputs/audit_top30.csv` |
| Weekly snapshots and forward validation | `outputs/history/`, `outputs/forward_validation.json` |
| Prediction model ratings and backtest | `docs/prediction.html`, `outputs/backtest_report.json`, `outputs/table_backtest.md` |
| Comparison with UFC media panel, Meta, Sherdog, Fight Matrix, ESPN | `outputs/compare_report.md`, `outputs/compare_flags.csv` |
| Card-quality index and supply facts | `outputs/card_quality_*.csv`, `outputs/card_quality_supply.json` |

## Headline results (as of 2026-09-26, method v1.0 frozen 2026-10-01)

Prediction, held-out 2020-2026 (3,390 bouts; parameters fixed by a 520-point grid on 2010-2019 and scored once):

| Model | Log loss | Brier | Accuracy |
|---|---|---|---|
| Coin flip | 0.693 | 0.250 | 50.0% |
| Results-only Elo, tuned | 0.674 | 0.241 | 58.1% |
| Performance-adjusted Elo (in-fight dominance) | 0.663 | 0.235 | 60.6% |

The log-loss gain of 0.011 has a 95% event-block bootstrap interval of 0.006 to 0.016 (McNemar exact p = 0.002 on the picks). On the 1,445 held-out bouts with closing odds (2020-2023) the de-vigged market scored 0.609 log loss and 67.1% accuracy against the model's 0.669 and 60.0%: the model is a transparent rating, not a betting edge. The first-listed (red corner) fighter wins 57.2% of held-out bouts against 53.5% predicted; the model carries no corner term. Full table: `outputs/table_backtest.md`; per-bout ledger: `data/processed/bouts_rated.csv`.

Card quality, 203 cards from 2022 to Sept 2026: numbered events average 2.19 champion-or-top-10 bouts per card (1.26 excluding title bouts) against 0.72 (0.71) for Fight Nights; 44% of Fight Nights carry none. Fighters starting a year inside a division top 11 average 1.30 to 1.44 bouts that year and 12% to 17% do not fight at all.

Resume board (REAL v1.0): a retrospective reconstruction over 127 boards is reported in `METHODOLOGY.md` section 8 and is not a forward test. The prospective test is pre-registered in `PREREGISTRATION.md` and starts with the first event after Oct 1, 2026. Data rights and redistribution basis: `DATA_LICENSE.md`.

## Pre-event picks

Every Monday and Friday the pipeline reads the upcoming UFC schedule, writes a pick for each bout inside the next three weeks to `predictions/picks.csv` (frozen performance-adjusted Elo probability, pick, confidence band, provisional flag, UTC timestamp) and never edits it. After each card the picks are graded from UFCStats and the running record (accuracy with interval, log loss, calibration by confidence band, baselines on the same bouts) goes to `outputs/picks_summary.json` and `docs/picks.html`. Each row also carries the pick of shadow v1.1 (`src/mmalab/shadow.py`: Elo re-tuned walk-forward over 2011 onward with a red-corner term, plus a logistic layer on age, layoff, experience, height and five-round bouts; development results in `outputs/shadow_v11_report.json`), which is graded alongside v1.0 and adopted only under PREREGISTRATION.md appendix B. Rules: PREREGISTRATION.md, appendices A and B. Settings: `config/picks.yaml`; `publish_page: true` adds the page to the site navigation.

## Build it yourself, step by step

Measure twice, cut once. Each step has a check so you know it worked before moving on.

### Phase 0: prerequisites (10 minutes)

1. Python 3.11 or newer (`python3 --version`), git, and a GitHub account.
2. Clone or unzip this repo, then from its root:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Check: `python3 -c "import pandas, yaml, matplotlib; print('ok')"` prints `ok`.

### Phase 1: data (2 minutes)

The raw CSVs come from [Greco1899/scrape_ufc_stats](https://github.com/Greco1899/scrape_ufc_stats), which re-scrapes UFCStats after every event, and the 2014-2023 closing odds from [jansen88/ufc-data](https://github.com/jansen88/ufc-data). `data/raw/` already holds a copy.

1. To refresh: `bash scripts/refresh_data.sh --quick` (downloads six CSVs, rebuilds everything except the grid search).
2. Check: the first data row of `data/raw/ufc_event_details.csv` is the most recent event.

Why this source: UFCStats is the official stats provider's public site, it goes back to 1994, and the round-level table (strikes, knockdowns, takedowns, control time) is what makes the performance adjustment possible.

### Phase 2: clean tables (30 seconds)

```bash
PYTHONPATH=src python3 -m mmalab.ingest
PYTHONPATH=src python3 -m mmalab.bout_stats
```

`ingest.py` writes `data/processed/bouts.csv` (one row per bout), `round_stats.csv`, and `fighters.csv`. `bout_stats.py` collapses the rounds into per-bout totals and the dominance differential.

Check: ingest prints `unmatched event dates: 0`, and bout_stats prints that the dominance sign agrees with the winner about 86% of the time.

### Phase 3: Elo engine and backtest (4 minutes)

```bash
PYTHONPATH=src python3 -m mmalab.backtest
```

What it does, in order: (1) scores an untuned classic Elo, (2) grid-searches K, the new-fighter multiplier, layoff regression, dominance weight, and win and finish floors on 2010-2019 bouts by log loss, (3) evaluates the winner and the best results-only model once on 2020-2026, (4) compares against de-vigged closing odds on the 3,499 bouts where both exist, (5) writes calibration and year-by-year tables.

Why the split matters: any number reported from the tuning window is optimistic. Only the 2020-2026 column in `outputs/table_backtest.md` should be quoted.

Check: `outputs/backtest_report.json` shows `tuned_test.log_loss` below `classic_tuned_test.log_loss`.

### Phase 4: rankings with adjustable weights (1 minute)

```bash
PYTHONPATH=src python3 -m mmalab.rankings            # as of the latest event
PYTHONPATH=src python3 -m mmalab.rankings 2025-12-31 # as of any past date
```

Edit `config/weights.yaml` to change the six weights (they must sum to 1), the active window, or the Elo parameters, then rerun. The stability band per fighter comes from 300 random weight vectors near yours, so you can see which placements are robust and which are a coin flip.

Check: `outputs/composite_boards.md` lists a champion (C) above each numbered board. If a division's champion holds the belt without a title bout in the data (promotion from interim), add them to `config/champions_override.yaml`.

### Phase 5: card-quality index (10 seconds)

```bash
PYTHONPATH=src python3 -m mmalab.card_quality
```

Positions are computed on each event's date from pre-fight ratings among fighters active in the prior 18 months, so no bout is judged with hindsight.

### Phase 6: figures and site (10 seconds)

```bash
PYTHONPATH=src python3 -m mmalab.figures
PYTHONPATH=src python3 -m mmalab.publish
```

Or everything at once: `PYTHONPATH=src python3 -m mmalab.run_all` (add `--quick` to skip the grid search).

### Phase 7: publish (20 minutes, once)

1. Create a public GitHub repo (SSAC requires a public repository with the data). Push this folder.
2. Repo settings, Pages, source: Deploy from branch, branch `main`, folder `/docs`. The boards are live at `https://<user>.github.io/<repo>/` within a minute.
3. Actions tab: enable workflows. `.github/workflows/weekly.yml` rebuilds every Monday and commits the new boards, so the site updates itself after each event.
4. For write-ups, a free Substack pointing at the Pages URL is enough. No website build needed.

## Repository layout

```
config/weights.yaml            all tunable numbers, documented inline
config/champions_override.yaml champions the bout data cannot infer
data/raw/                      UFCStats CSVs and the odds file
data/processed/                clean tables (bouts.csv, bouts_with_stats.csv, ...)
src/mmalab/ingest.py           raw CSVs -> clean tables
src/mmalab/bout_stats.py       round stats -> per-bout totals and dominance differential
src/mmalab/elo.py              the rating engine (classic and performance-adjusted)
src/mmalab/backtest.py         grid search, held-out evaluation, market comparison
src/mmalab/resume.py           resume rating engine (judges + stats, loss rules, official ranks)
src/mmalab/resume_board.py     REAL boards: ledger, form, division, head-to-head, title cycle, audit
src/mmalab/official_ranks.py   official UFC rank on any date (2013+)
src/mmalab/history.py          snapshots, movement arrows, forward validation
src/mmalab/methodology.py      writes METHODOLOGY.md from the live config
src/mmalab/compare.py          comparison with public boards
src/mmalab/rankings.py         legacy six-dimension composite (v0.x)
src/mmalab/card_quality.py     top-10 vs top-10 bouts per card, supply facts
src/mmalab/figures.py          paper figures and table
src/mmalab/publish.py          docs/index.html for GitHub Pages
src/mmalab/run_all.py          the whole pipeline in order
scripts/refresh_data.sh        download fresh CSVs and rebuild
paper/abstract_ssac27.md       the SSAC27 abstract (under 500 words)
```

## Method notes

Elo update: `R' = R + K * m * (S - E)` with `E = 1 / (1 + 10^((R_opp - R) / 400))`. In the performance-adjusted variant, `S = (1 - w) * result + w * sigmoid(dominance / scale)`, then floored so a win scores at least 0.5 and a finish at least 0.75 (the interpretable model in `config/weights.yaml`). K is multiplied by 2 for a fighter's first five UFC bouts. After a layoff longer than 365 days the rating regresses 25% toward 1500 per additional year.

Dominance per minute: `(sig strikes diff + 5 * knockdown diff + 2 * takedown diff + 2 * sub attempt diff + control seconds diff / 60) / minutes`. The weights are stated up front; the backtest, not taste, decided how much of the update listens to them.

Known limits: no regional (pre-UFC) records, so debutants start at 1500; no injury or contract data; champion status only from title bouts plus the override file; positions in the card-quality index come from the rating, not the official board.

## Citation

Smith, B. (2026). REAL Fighter Rankings: resume rankings, performance-adjusted Elo, and a card-quality index for the UFC (Version 1.0). GitHub repository.
