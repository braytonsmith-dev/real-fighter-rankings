"""
verify_placement.py - Compare the sequential placement rules with the placement solver on real boards.

    PYTHONPATH=src python3 scripts/verify_placement.py [--ride all|recent|none] [--no-waive] [--detail N] DATE ...

For each as_of DATE (YYYY-MM-DD; default: six event dates over 2024-2026 plus today) the script runs
resume_board.build(stability=False) once, captures the scored contender frame and the resume `out` frame
on their way into head_to_head() through a wrapper installed on the module for the duration of the call,
and then runs placement.apply_to_board on the same inputs. It prints, per date and division, how many
positions differ, which collected constraints the sequential result violates, which lifts the sequential
rule applied that do not qualify against the score order, and whether the solver violates anything.
Nothing is written to disk.
"""
from __future__ import annotations

import argparse
import random
import sys
import time

import pandas as pd

from mmalab import placement as pl
from mmalab import resume_board as rb

DEFAULT_DATES = ["2024-04-14", "2024-09-15", "2025-01-19", "2025-06-29", "2025-12-07", "2026-05-10",
                 str(pd.Timestamp.today().date())]


def capture(as_of: str) -> dict:
    """build() with the two rules wrapped so their inputs and outputs can be inspected afterwards."""
    cap: dict = {}
    orig_h2h, orig_tc = rb.head_to_head, rb.title_cycle

    def h2h(board, out, as_of_ts, max_gap, max_years, max_gap_recent=None):
        cap.update(cont_pre=board.copy(), out=out, as_of=as_of_ts,
                   h2h=dict(max_gap=max_gap, max_years=max_years, max_gap_recent=max_gap_recent))
        res, notes = orig_h2h(board, out, as_of_ts, max_gap, max_years, max_gap_recent)
        cap["h2h_notes"] = list(notes)
        return res, notes

    def tc(cont, out, as_of_ts, tcfg):
        cap["tc"] = dict(tcfg)
        res, notes = orig_tc(cont, out, as_of_ts, tcfg)
        cap["cont_final"] = res.copy()
        cap["tc_notes"] = list(notes)
        return res, notes

    rb.head_to_head, rb.title_cycle = h2h, tc
    try:
        rb.build(as_of=as_of, stability=False)
    finally:
        rb.head_to_head, rb.title_cycle = orig_h2h, orig_tc
    return cap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dates", nargs="*", default=DEFAULT_DATES)
    ap.add_argument("--ride", default="all", choices=["all", "recent", "none"])
    ap.add_argument("--no-waive", action="store_true")
    ap.add_argument("--detail", type=int, default=2, help="print the first N differing divisions in full")
    args = ap.parse_args()
    pd.set_option("display.width", 220)
    rows, viol_rows, extra_rows, explain = [], [], [], []
    shown = 0
    for as_of in args.dates:
        t0 = time.time()
        cap = capture(as_of)
        t_build = time.time() - t0
        pre, fin, out, as_of_ts = cap["cont_pre"], cap["cont_final"], cap["out"], cap["as_of"]
        cfg = {"head_to_head": dict(cap["h2h"], ride_settled=args.ride),
               "title_cycle": dict(cap["tc"], reserved_waives_h2h=not args.no_waive)}
        t0 = time.time()
        ctx = pl.build_context(out, as_of_ts, cfg)
        solved, _, report = pl.apply_to_board(pre, out, as_of_ts, cfg, ctx)
        t_solve = time.time() - t0
        seq_lifts = set()
        for n in cap["h2h_notes"]:
            div, rest = n.split(": ", 1)
            w, rest = rest.split(" moved above ", 1)
            seq_lifts.add((div, w, rest.split(" (won ")[0]))
        label = str(as_of_ts.date())
        for div, g in pre.groupby("division"):
            score = list(g.sort_values("pos")["fighter"])
            seq = list(fin[fin["division"] == div].sort_values("pos")["fighter"])
            sol = list(solved[solved["division"] == div].sort_values("pos")["fighter"])
            rep = report["divisions"][div]
            cons = rep["constraints"]
            v_seq, v_sol = pl.violations(seq, cons), pl.violations(sol, cons)
            assert set(v_sol) <= set(rep["dropped"]), f"solver violates a kept constraint: {div} {label} {v_sol}"
            base = pl.solve(score, cons, waive=not args.no_waive)
            for s in range(3):
                shuffled = list(cons)
                random.Random(s).shuffle(shuffled)
                assert pl.solve(score, shuffled, waive=not args.no_waive) == base, "constraint order changed the result"
            h2h_pairs = {(c.fighter, c.other) for c in cons if c.kind == pl.PRECEDENCE and c.reason == pl.H2H}
            extra = {(w, l) for d, w, l in seq_lifts if d == div} - h2h_pairs
            for w, l in sorted(extra):
                date = ctx.last_meeting[tuple(sorted((w, l)))][0]
                extra_rows.append(dict(date=label, division=div, lift=f"{w} above {l}", won=str(date.date()),
                                       gap_at_score=score.index(w) - score.index(l),
                                       allowed=ctx.max_gap_recent if (as_of_ts - date).days <= 365 else ctx.max_gap))
            n_diff = sum(a != b for a, b in zip(seq, sol))
            rows.append(dict(date=label, division=div, n=len(score), cons=len(cons), caps=sum(c.kind == pl.CAP for c in cons),
                             seq_top15=sum(a != b for a, b in zip(seq[:15], score[:15])), sol_top15=rep["top15_changed"],
                             diff=n_diff, diff_top15=sum(a != b for a, b in zip(seq[:15], sol[:15])),
                             seq_viol=len(v_seq), sol_viol=len(set(v_sol) - set(rep["dropped"])), waived=len(rep["dropped"]),
                             seq_extra=len(extra), seq_inv=len(pl.inverted_rides(seq, cons)),
                             sol_inv=len(pl.inverted_rides(sol, cons)), sol_maxdisp=rep["max_displacement"]))
            for c in v_seq:
                viol_rows.append(dict(date=label, division=div, constraint=c.describe(),
                                      score=f"#{score.index(c.fighter) + 1} vs #{score.index(c.other) + 1}",
                                      sequential=f"#{seq.index(c.fighter) + 1} vs #{seq.index(c.other) + 1}",
                                      solver=f"#{sol.index(c.fighter) + 1} vs #{sol.index(c.other) + 1}"))
            if n_diff:
                explain.append((label, div, [f"{f}: score #{score.index(f) + 1}, sequential #{seq.index(f) + 1}, solver #{sol.index(f) + 1}"
                                             for f in score if seq.index(f) != sol.index(f)],
                                [c.describe() for c in v_seq], [f"{w} above {l}" for w, l in sorted(extra)],
                                [c.describe() for c in rep["dropped"]]))
                if shown < args.detail:
                    shown += 1
                    top = min(max(max(i for i, (a, b) in enumerate(zip(seq, sol)) if a != b) + 2, 10), len(score))
                    print(f"\n===== {label} {div} =====")
                    print(pd.DataFrame({"#": range(1, top + 1), "score order": score[:top], "sequential": seq[:top],
                                        "solver": sol[:top]}).to_string(index=False))
                    print("constraints:")
                    for c in cons:
                        if c.kind != pl.RIDE:
                            print("   ", c.describe(), "(dropped)" if c in rep["dropped"] else "")
                    print("sequential notes:")
                    for n in cap["h2h_notes"] + cap["tc_notes"]:
                        if n.startswith(div + ":"):
                            print("   ", n)
                    print("solver notes:")
                    for n in rep["notes"]:
                        print("   ", n)
        print(f"{label}: build {t_build:.0f}s, solver {t_solve:.2f}s, constraints {report['constraints']}, "
              f"top-15 spots off score order: sequential {sum(r['seq_top15'] for r in rows if r['date'] == label)}, "
              f"solver {report['top15_changed']}", flush=True)

    df = pd.DataFrame(rows)
    print(f"\n===== PER DATE AND DIVISION (ride_settled={args.ride}, waive={not args.no_waive}) =====")
    print(df.to_string(index=False))
    print("\n===== PER DATE =====")
    print(df.groupby("date").agg(divisions=("division", "size"), fighters=("n", "sum"), cons=("cons", "sum"), caps=("caps", "sum"),
                                 diff=("diff", "sum"), diff_top15=("diff_top15", "sum"), divs_differing=("diff", lambda s: int((s > 0).sum())),
                                 seq_viol=("seq_viol", "sum"), sol_viol=("sol_viol", "sum"), waived=("waived", "sum"),
                                 seq_extra=("seq_extra", "sum"), seq_inv=("seq_inv", "sum"), sol_inv=("sol_inv", "sum")).to_string())
    print(f"\nTOTAL positions differing {df['diff'].sum()} | top-15 positions differing {df['diff_top15'].sum()} | "
          f"divisions differing {int((df['diff'] > 0).sum())} of {len(df)} | sequential violates {df['seq_viol'].sum()} constraints | "
          f"solver violates {df['sol_viol'].sum()} | waived or dropped {df['waived'].sum()} | "
          f"sequential non-qualifying lifts {df['seq_extra'].sum()} | settled results inverted: sequential {df['seq_inv'].sum()}, solver {df['sol_inv'].sum()}")
    print("\n===== CONSTRAINTS THE SEQUENTIAL RESULT VIOLATES =====")
    print(pd.DataFrame(viol_rows).to_string(index=False) if viol_rows else "none")
    print("\n===== LIFTS THE SEQUENTIAL RULE APPLIED THAT DO NOT QUALIFY AGAINST THE SCORE ORDER =====")
    print(pd.DataFrame(extra_rows).to_string(index=False) if extra_rows else "none")
    print("\n===== EVERY DIFFERING DIVISION =====")
    for label, div, moved, viol, extra, dropped in explain:
        print(f"\n{label} {div}: {len(moved)} fighters placed differently")
        for m in moved:
            print("   ", m)
        for title, items in (("sequential violates", viol), ("sequential non-qualifying lifts", extra), ("solver waived or dropped", dropped)):
            if items:
                print(f"    {title}: " + "; ".join(items))


if __name__ == "__main__":
    sys.exit(main())
