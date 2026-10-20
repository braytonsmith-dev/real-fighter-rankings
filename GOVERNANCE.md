# Governance: how a method change is proposed, tested, labelled and announced

REAL publishes rankings that people quote, and it runs a pre-registered forward test of its own method. Both are only worth
something if changes follow written rules. These are the rules. They bind the curator as much as any contributor.

## 1. Three kinds of change

| Kind | Examples | Version | Where logged |
|---|---|---|---|
| Rule change | a weight, a threshold, a tier value, a new or removed rule, a change to the rating engine | new minor version (`1.1`, `1.2`) | CHANGELOG.md, METHODOLOGY.md changelog, the version's config file |
| Display or documentation change | page layout, labels, footers, wording, new tables | patch (`1.0.1`) | CHANGELOG.md |
| Data correction | a name alias, a corrected result, a dated roster fact (injury, retirement, division move) | no version change | CHANGELOG.md under "Data corrections", and the weekly commit message with the source |

A data correction records a fact about the world; it never changes a rule and is applied from the day it is entered. Published
snapshots are never rewritten (PREREGISTRATION.md section 3). If a correction would have changed a snapshot, the original stands in
the primary analysis and the corrected figure is reported as a sensitivity result (section 1 of the protocol).

## 2. The registered method is frozen

`VERSION` names the registered method (v1.0, frozen Oct 1, 2026, through Sept 30, 2027). Its configuration is `config/weights.yaml`,
whose SHA-256 is recorded in PREREGISTRATION.md and checked by `tests/test_config.py`. No parameter in that file changes during the
registered period. The registered board is always built, snapshotted to `outputs/history/` and published at `docs/index.html`.

## 3. How a new version is made

1. Proposal. Write the problem down with evidence (an audit finding, a worked example, a measured bias). State which v1.0 principle
   the change keeps and which it alters.
2. Configuration. Put the new rules in `config/board_v<major>_<minor>.yaml` as overrides over the frozen file. Never edit
   `config/weights.yaml`. Every override line carries a comment with the old value and the reason.
3. Measurement before adoption. Score the candidate on the tuning panel (`python -m mmalab.board_tune`) and with full event-eve
   rebuilds (`python -m mmalab.board_versions --backfill 36`) on exactly the same bouts as v1.0, with paired event-block bootstrap
   intervals. Report concordance and log loss for the whole population and for the top 15. Report the face-validity table (the
   placements the change was meant to fix, and the largest unintended moves). Never fit to the face-validity anchors.
4. Pre-registration. Before the first shadow snapshot is committed, add a dated appendix to PREREGISTRATION.md with the version's
   adoption criterion. The appendix never alters v1.0's endpoints, populations, baselines or tests.
5. Shadow publication. The version is built every week beside v1.0 (`python -m mmalab.board_versions`), with its own snapshot
   directory, its own forward-validation files and its own page labelled as a candidate. The registered page says it exists.
6. Adoption. When the criterion is met, `VERSION` moves, the page roles swap, and CHANGELOG.md records the date and the evidence.
   Until then the registered board is the one quoted as REAL's ranking.

## 4. What is never done

- Hand-placing a fighter. A placement that looks wrong is a rule problem; fix the rule for everyone or leave it.
- Changing a rule to fix one week's board. A change needs the measurement in step 3 and a changelog entry.
- Editing a published snapshot, a locked pick or a graded result.
- Describing an in-sample reconstruction as a forward test. Retrospective figures are labelled retrospective everywhere.
- Fitting rules to the official UFC rankings or to any personal list. The curator's favourites page is separate from every board and plays no part in any rule.

## 5. Announcing a change

Each adopted version or data correction is announced in the same commit that ships it: CHANGELOG.md entry, METHODOLOGY.md
regenerated, the site footer showing the version and build commit, and a README line when the headline method changes. A
BREAKING-style summary for social posts is derived from the changelog, never written first.

## 6. Who decides

The curator (the repository owner) approves every rule change and signs the changelog entry by committing it. Contributors propose
through pull requests that include steps 1 to 4. Automated runs (the weekly workflow) never change a rule; they only add dated
facts to the override files and regenerate outputs.
