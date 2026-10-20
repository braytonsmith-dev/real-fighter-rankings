# Experiments: how a test is registered, run and kept

REAL changes only on evidence (GOVERNANCE.md). This directory is where the evidence lives, including the evidence
against ideas that were tried and turned down, so the same idea is not re-run by accident and a later improvement can
start from what was already learned.

## Files

| Path | What it is |
|---|---|
| `register.jsonl` | one JSON object per experiment, append-only, written by `mmalab.experiments.record()` |
| `REGISTER.md` | the same entries rendered for reading; regenerate with `python -m mmalab.experiments` |
| `results/<id>/` | the small result files an entry points to: parameter dicts, summaries, per-year tables (JSON or CSV) |

Large intermediate objects (the tuning panels, the per-date boards) are not committed; the entry names the script and
the commit that rebuild them.

## Protocol

1. Register before running when the test is expensive or will decide a rule: write the question, the method and the
   candidate, with `decision: "running"`, and fill the results with `update()` afterwards. A quick pilot may be
   registered after the fact in the same turn it was run; it still gets the full entry.
2. One question per entry. A sweep is one entry with the whole table in its results file.
3. Method must say: data window, number of boards or snapshots, number of evaluation bouts and how they were selected,
   the metric (concordance, log loss with the slope fitted how), the baseline scored on the same bouts, and the
   interval method (paired event-block bootstrap unless stated).
4. Candidate must be reproducible: the exact parameter dict or override block, or the script name and commit.
5. Results report the whole population and the top 15, and the paired difference against the baseline with its 95%
   interval. In-sample numbers are labelled in-sample; held-out numbers say what was held out.
6. Face validity is reported, never fitted: the placements the change was meant to fix and the largest unintended moves.
7. Decision is one of adopted, rejected, parked, running, superseded, informational, with the reason in one or two
   sentences. A rejection records what would change the verdict.
8. The harness records automatically: `board_tune` walk-forwards, engine sweeps and candidate comparisons call
   `record()` when they finish, so a result is never only in a terminal.

## Template

```python
from mmalab.experiments import record
record(
    exp_id=None,                      # or a fixed id; None takes the next EXP-YYYY-MM-DD-nn
    title="Short name of the test",
    question="What would change if ...?",
    method={"instrument": "board_tune walk-forward", "window": "2014-01 to 2026-10, boards every 14 days",
            "bouts": 3656, "metric": "concordance; log loss, slope fitted on training years",
            "baseline": "v1.0 rules on the same bouts", "interval": "paired event-block bootstrap, 5000 draws"},
    candidate={"loss": {"mode": "tiers", "tiers": [0.25, 0.5, 0.75, 1.0]}},
    results={"concordance": "0.5795 vs 0.5737", "log_loss": "0.6746 vs 0.6771 (diff -0.0025, CI -0.0045 to -0.0005)"},
    face_validity={"Usman (WW)": "5 (was 9)", "largest unintended move": "Jim Miller 11 to 19"},
    decision="parked",
    reason="Improves the whole population, not the top 15; revisit with the engine sweep.",
    files={"summary.json": {...}},
)
```
