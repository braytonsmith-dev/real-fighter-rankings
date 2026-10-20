# Market baseline for the pre-event picks

Written Oct 20, 2026. The picks ledger (`predictions/picks.csv`) publishes the frozen model's probability for every UFC bout up to three weeks out and grades it afterwards. The only odds series in the repository ends in December 2023, so from the v1.0 freeze onward nobody could tell whether a miss was the model's or everyone's. `src/mmalab/odds.py` closes that gap with a second append-only ledger, `predictions/market_at_lock.csv`, holding the de-vigged bookmaker consensus for each pending bout at two moments: when the pick was locked and on the last scheduled run before the event. The feature is off until the owner creates an API key.

## 1. Turning it on

1. Create a key. Sign up at [the-odds-api.com](https://the-odds-api.com). The free Starter plan ("500 credits per month", "Most bookmakers", "All betting markets", no historical odds) is enough: one call costs one credit per region per market, the weekly job makes one call per run with three regions and one market, so about nine runs a month use about 27 credits.
2. Add the key to GitHub. Repository Settings, Secrets and variables, Actions, New repository secret: name `ODDS_API_KEY`, value the key. The code reads the key from that environment variable only (`odds.api_key_from_env`); it is never read from or written to a file in the repository, and the request URL is logged with the key blanked.
3. Expose the secret to the rebuild step in `.github/workflows/weekly.yml`:

   ```yaml
         - run: bash scripts/refresh_data.sh --quick
           env:
             ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
   ```

4. Flip `enabled: false` to `enabled: true` in `config/odds.yaml`. Leave `store_raw_prices: false` (section 3).
5. Check locally before the next scheduled run: `ODDS_API_KEY=... PYTHONPATH=src python3 -m mmalab.odds --dry-run` fetches once, prints the pending picks that matched a market bout, and writes nothing. `PYTHONPATH=src python3 -m mmalab.odds --baseline` prints the comparison from the ledgers on disk.

If the key is missing or the API is unreachable the run prints one line starting with `odds:` and the rest of the rebuild continues; the market ledger simply gains no rows that run. Unmatched names are reported the same way picks.py reports ESPN misses, and a spelling difference is fixed by adding a line to `config/name_aliases.yaml` (market spelling: UFCStats spelling).

## 2. What is recorded

One call per run to `GET /v4/sports/mma_mixed_martial_arts/odds/?regions=us,uk,eu&markets=h2h&oddsFormat=decimal` (the one MMA sport key the API offers; UFC bouts are picked out by matching the name pair and date to the picks ledger). For every bookmaker that quotes both fighters, the two decimal prices are turned into implied probabilities (1/price) and normalised to sum to one, which removes the over-round in proportion; the per-book probabilities are then averaged across books. Lay prices on exchanges (`h2h_lay`) and any "Draw" line are ignored; a book without a valid price above 1.0 for both fighters is dropped; a bout needs at least `min_books` books.

Matching mirrors `picks.py`: names go through `mmalab.compare.norm` and the alias map in `config/name_aliases.yaml`, and the bout's commence time (UTC) must be within `window_days` of the ledger's event date. Probabilities are re-oriented to the pick's `fighter_a` / `fighter_b`.

Two snapshot kinds, keyed with the bout:

| `snapshot_kind` | Written by | Meaning |
|---|---|---|
| `lock` | the first run that sees the bout in both the market and the pending picks | the market at (or shortly after) the time the model's pick was locked |
| `last_before_event` | the run whose next scheduled run (Mondays and Fridays 13:00 UTC, `schedule_utc` in the config) falls after the bout's commence time | the closest thing to a closing line the weekly cadence can give; for a Saturday card it is the Friday 13:00 UTC snapshot |

Rows are never edited. A re-run, a manual `workflow_dispatch` on a Saturday, or the same bout re-listed with the fighters swapped writes nothing new for a key that already exists. A bout whose commence time has passed gets no row, so a late Monday run after a Sunday card records nothing for it.

Columns of `predictions/market_at_lock.csv`: `pick_id, fighter_a, fighter_b, event_date, snapshot_kind, fetched_at_utc, commence_time_utc, n_books, p_a_market, p_b_market, market_favourite, price_a_min, price_a_max, price_b_min, price_b_max, provider, regions, markets`. The four price columns stay blank unless `store_raw_prices` is true.

## 3. What is stored publicly, and why

The Odds API's terms and conditions (https://the-odds-api.com/terms-and-conditions.html, "Last updated: 31 August 2026") say, in the Restrictions section:

> "Do not resell, repackage, or redistribute our data as a standalone data product."
> "This includes, but is not limited to, offering our data through your own API, data feed, downloadable files, or any other format intended to serve as a source of raw data for others."
> "We support and encourage the use of our data in websites, mobile apps, dashboards, analytical tools, including commercial use, provided our data is not the primary product being sold or redistributed."

and list among the permitted uses:

> "Storing our data and retaining it indefinitely"
> "Displaying our data in a UI, website, or mobile app, including for commercial use"
> "Using our data in research papers and analytical dashboards"
> "Calculating and displaying values you derive from our data"
> "Using our data to train statistical and machine learning models"

followed by:

> "We mainly prohibit reselling the data as a raw data feed, i.e. a competing product."
> "Attribution to The Odds API is not required, but is always appreciated."
> "If we reasonably suspect a violation of these terms, including the resale or redistribution of our data" [...] "we reserve the right to revoke your API key and block future access."
> "If you are unsure whether your use case is permitted, please contact us."

Reading of those clauses for this repository: storing the fetched data, using it in a research paper and publishing values derived from it are expressly permitted; a CSV of per-bookmaker prices in a public repository is a "downloadable file" that others could use as raw data, which is the one thing the terms forbid. The ledger therefore stores only derived values by default: the de-vigged consensus probability for each fighter, the market favourite and the number of books behind the number. Per-bookmaker prices and the min/max price range are written only if the owner sets `store_raw_prices: true` (the range goes into the ledger and one row per bookmaker into `predictions/market_books.csv`); raw API responses are never written to disk under either setting. Attribution is not required but the `attribution` string from the config is carried into `outputs/picks_summary.json` and should appear wherever the market numbers are shown. The terms also ask users to encourage responsible gambling; the picks page already states that nothing on it is betting advice.

Other facts checked on Oct 20, 2026:

- Pricing (https://the-odds-api.com/): Starter, "FREE", "500 credits per month", historical odds excluded; paid tiers 20K ($30), 100K ($59), 5M ($119) and 15M ($249) per month, all with historical odds.
- Usage (https://the-odds-api.com/liveapi/guides/v4/): "The usage quota cost is 1 per region per market"; "If no events are returned, the request will not count against the usage quota"; "Events may be unavailable if the sport is not in season"; response headers `x-requests-remaining`, `x-requests-used`, `x-requests-last`; rate limiting answers with HTTP 429 ("try spacing out requests over several seconds"). The historical odds endpoint "is only available on paid usage plans".
- Sport key (https://the-odds-api.com/sports-odds-data/sports-apis.html): group "Mixed Martial Arts", title "MMA", key `mma_mixed_martial_arts`; "All usage plans give access to all available sports".
- Regions and markets: `us`, `us2`, `uk`, `eu`, `au`; `h2h` (moneyline), `spreads`, `totals`, `outrights`; lay odds for exchanges come back as `h2h_lay`. Bookmaker lists by region are at https://the-odds-api.com/sports-odds-data/bookmaker-apis.html; a few books there (Caesars, Fanatics, Bet365 AU and others) are marked "only available on paid subscriptions", so the free plan averages a slightly smaller set.
- Governing law: New South Wales, Australia. The provider is The Odds API Pty Ltd.

Alternatives considered:

- OddsAPI.io (https://odds-api.io/terms, "Last Updated: October 4, 2026"): "You may not resell, redistribute, or sublicense our data to third parties without prior written consent from Odds API"; no clause permits derived values or storage; the pricing page says "New free keys are paused" and the cheapest plan is Solo at 49 GBP a month. Not suitable for an open, no-budget project.
- Pinnacle (https://www.pinnacle.com/en/api): access is by application only ("API access can be granted for the purposes of academic research", with the commercial team deciding) and "Any and all content on the website (desktop and mobile), including sports odds, are proprietary and may not be copied or disseminated without the express written consent of Pinnacle." Publishing anything derived from it would need that consent in writing.

The Odds API is the only one of the three with a free tier and an express permission to store the data and publish derived values. `DATA_LICENSE.md` carries the corresponding row.

## 4. How the baseline is reported

`odds.market_baseline(picks_df, market_df)` scores, on the graded picks that have a market row, the market favourite's accuracy and the de-vigged probability's log loss and Brier score next to the model's on exactly the same bouts, separately for the `lock` and `last_before_event` snapshots. It also reports how often the model's pick and the market favourite agree and the split record on the bouts where they disagree, which is the direct answer to "was the miss the model's or everyone's". Its `baselines_same_bouts` block has the same shape as the other baselines in `outputs/picks_summary.json` (`n, accuracy, log_loss, model_accuracy_same_bouts, model_log_loss_same_bouts`) so the picks page's baseline table can show the market rows without a new template. The favourite is `fighter_a` when `p_a_market >= 0.5`, the model's own tie rule; a market at exactly 0.5 is counted in `pickem_bouts`.

Limits worth stating with the numbers: the `lock` snapshot is taken up to three weeks out, when lines are thin (`n_books` says how thin); the `last_before_event` snapshot is Friday 13:00 UTC for a Saturday card, roughly a day and a half before the closing line; the consensus is an unweighted mean across books of a two-way normalisation, which treats the over-round as split in proportion to the implied probabilities; the free plan's bookmaker set is a subset of the paid one. PREREGISTRATION.md section 6 already lists "closing market favorite and de-vigged closing probability, where a lawfully usable odds series exists" as a baseline; the `last_before_event` snapshot is the lawful stand-in for the closing line from the first event after the feature is enabled, and nothing earlier can be back-filled on the free plan.

## 5. Hooks in picks.py

`odds.py` touches nothing in `picks.py`; three lines wire it in. In `main()`, right after `ledger = lock(upcoming, data_through)` and before `grade()`, so picks locked this run get their lock-time market in the same run:

```python
from mmalab import odds
odds.snapshot(ledger)        # pending picks only; prints one "odds:" line and returns an empty frame while enabled: false
```

In `summarize()`, before `picks_summary.json` is written (the `baselines_same_bouts` block exists only when there are graded bouts, hence `setdefault`):

```python
mk = odds.market_baseline(ledger, odds.load_market())
out["market"] = mk
out.setdefault("baselines_same_bouts", {}).update(mk["baselines_same_bouts"])
```

The market rows then appear in the baseline table on `docs/picks.html` with no change to `publish.py`, because each entry has the keys that table reads (`n, accuracy, log_loss, model_accuracy_same_bouts, model_log_loss_same_bouts`). `out["market"]["attribution"]` is the text to show next to them.

## 6. Files

```
config/odds.yaml                   provider, sport key, regions, markets, budget, window, store_raw_prices, schedule, attribution
src/mmalab/odds.py                 client, parser, consensus, matcher, append-only recorder, baseline, CLI
predictions/market_at_lock.csv     the public market ledger (created on the first enabled run)
predictions/market_books.csv       per-bookmaker rows, only when store_raw_prices is true
tests/test_odds.py                 fixture payload in the documented v4 shape; no network
```
