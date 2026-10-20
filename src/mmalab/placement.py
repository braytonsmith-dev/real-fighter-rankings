"""
placement.py - One constrained ordering pass in place of the two sequential placement rules.

resume_board.build() scores every contender and then runs head_to_head() and title_cycle() in
sequence, each a hand-written loop over a mutable order. This module states the same rules as
typed constraints and solves them in one pass, so the result no longer depends on the order in
which meetings are processed, on the order the two rules run, or on the iteration order of the
title-cycle fixed-point loop.

Constraints (same semantics as the sequential rules):

  PRECEDENCE(winner above loser, date)   head-to-head: the winner of the most recent decided
      meeting of a pair within max_years sits above the loser when he sits 0 < gap <= allowed
      places below him, allowed = max_gap_recent for a meeting within 365 days, else max_gap.
      A close meeting older than a year settles nothing (and voids earlier meetings of the pair).
      A winner with a negative last five (more losses than wins in the last five decided bouts)
      forfeits the lift. The gap is measured in the SCORE order. The sequential rule measures it
      in the partially modified order, so a lift applied earlier can make a later pair qualify or
      stop qualifying: one source of its order dependence.
  CAP(fighter, min_position)              title cycle: a challenger who lost a title fight in the
      last `days` and has not earned release (one top-10 win, or two wins) is placed no higher
      than min_position. A champion who lost the belt while defending is exempt.
  PRECEDENCE(capped above victim, date)   anyone a capped fighter beat in the last 365 days stays
      below him (a hold: the victim waits, the capped fighter is not promoted by it).
  RIDE(winner with loser, date)           a settled result: the winner already sits above the loser
      in the score order. If a lift carries the loser up, the winner rides to the same spot, so a
      chain of other results cannot invert a decided meeting. A ride never holds anyone: a winner
      who is capped or held stays where the hard constraints put him and the result is reported as
      inverted. The sequential rule restores such a result only when it happens to process that
      meeting after the lift. config head_to_head.ride_settled: all (default), recent, none.

solve() is Kahn's topological sort over the hard precedence graph with a heap keyed by the
effective score position: the best score position among the fighter and every fighter he is
lifted over or rides with. That key lifts a winner into the loser's spot (the loser and everyone
below shift down one), which is what "moves directly above" means in the sequential rule; a plain
score-position key would instead drag the loser down to the winner. Positions 1..min_position-1
are reserved for fighters without a cap in the same pass; a fighter kept out of a reserved spot
only by a waiting capped fighter's head-to-head lift may take it and that lift is waived
(config title_cycle.reserved_waives_h2h, default true), which is how the sequential fill behaves:
only a recent victim cannot jump over the capped fighter. Constraints compose transitively, so a
chain of qualifying results can lift a fighter further than any single gap allowance. Cycles
(possible only through the victim holds, since head-to-head edges all point up the score order)
are broken by dropping the oldest meeting in the cycle, which keeps "the most recent meeting wins".

The functions below are pure: nothing here reads config files or writes outputs.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

PRECEDENCE = "precedence"
CAP = "cap"
RIDE = "ride"
H2H = "head-to-head"
SETTLED = "head-to-head settled"
TITLE_LOSS = "title-cycle"
VICTIM = "title-cycle victim"


@dataclass(frozen=True)
class Constraint:
    """A placement constraint. PRECEDENCE: `fighter` sits above `other`; with `lift` the fighter is promoted
    into the other's spot, without it the other is held below the fighter. CAP: `fighter` sits no higher
    than `min_position` (1-based). RIDE: `fighter` already sits above `other` and follows him up if he is
    lifted. `date` is the meeting date (precedence, ride) or the title loss (cap)."""
    kind: str
    fighter: str
    other: str = ""
    min_position: int = 0
    reason: str = ""
    date: pd.Timestamp | None = None
    lift: bool = True

    def describe(self) -> str:
        when = f" {self.date.date()}" if self.date is not None else ""
        if self.kind == CAP:
            return f"{self.fighter} no higher than #{self.min_position} ({self.reason}{when})"
        if self.kind == RIDE:
            return f"{self.fighter} rides with {self.other} ({self.reason}{when})"
        return f"{self.fighter} above {self.other} ({self.reason}{when})"


def precedence(winner: str, loser: str, reason: str, date: pd.Timestamp, lift: bool = True) -> Constraint:
    return Constraint(PRECEDENCE, winner, loser, 0, reason, pd.Timestamp(date), lift)


def cap(fighter: str, min_position: int, reason: str, date: pd.Timestamp) -> Constraint:
    return Constraint(CAP, fighter, "", int(min_position), reason, pd.Timestamp(date), False)


def ride(winner: str, loser: str, reason: str, date: pd.Timestamp) -> Constraint:
    return Constraint(RIDE, winner, loser, 0, reason, pd.Timestamp(date), True)


@dataclass(frozen=True)
class RuleContext:
    """Division-independent facts both rules read, computed once per board (build_context)."""
    as_of: pd.Timestamp
    max_gap: int
    max_gap_recent: int
    min_position: int
    last_meeting: dict[tuple[str, str], tuple[pd.Timestamp, str]]   # sorted pair -> (date, winner)
    negative_form: frozenset[str]
    capped: dict[str, pd.Timestamp]                                   # fighter -> title loss date
    beat_recently: dict[str, dict[str, pd.Timestamp]]                 # winner -> {loser: latest win date}
    ride_settled: str = "all"                                         # all | recent | none
    waive: bool = True                                                # title_cycle.reserved_waives_h2h


def _decided(out: pd.DataFrame) -> pd.DataFrame:
    return out[out["result_a"].isin([0.0, 1.0])]


def negative_form(out: pd.DataFrame) -> frozenset[str]:
    """Fighters with more losses than wins among their last five decided bouts (resume_board.last_five)."""
    from mmalab.resume_board import last_five       # lazy: resume_board imports this module once wired
    lf = last_five(out)
    if lf.empty:
        return frozenset()
    rec = lf["last5"].str.split("-", expand=True).astype(int)
    return frozenset(lf.index[rec[1] > rec[0]])


def capped_fighters(out: pd.DataFrame, as_of: pd.Timestamp, tc: dict) -> dict[str, pd.Timestamp]:
    """Losers of a title fight in the last tc['days'] who were not defending the belt and have not since
    earned release: tc['release_top10_wins'] top-10 wins (default 1) or tc['release_wins'] wins (default 2)."""
    t = out[out["title_fight"]].sort_values(["date", "bout_id"])
    holder: dict[str, str] = {}
    capped: dict[str, pd.Timestamp] = {}
    for x in t.itertuples():
        if x.result_a not in (0.0, 1.0):
            continue
        winner = x.fighter_a if x.result_a == 1.0 else x.fighter_b
        loser = x.fighter_b if x.result_a == 1.0 else x.fighter_a
        defending = (not x.interim) and holder.get(x.division) == loser
        if not x.interim:
            holder[x.division] = winner
        if (as_of - x.date).days <= int(tc["days"]) and not defending:
            capped[loser] = x.date
    d = _decided(out)
    for name, when in list(capped.items()):
        later = d[(d["date"] > when) & (((d["fighter_a"] == name) & (d["result_a"] == 1.0)) |
                                        ((d["fighter_b"] == name) & (d["result_a"] == 0.0)))]
        top10 = int(later["top10_win"].sum()) if "top10_win" in later.columns else 0
        if top10 >= int(tc.get("release_top10_wins", 1)) or len(later) >= int(tc.get("release_wins", 2)):
            capped.pop(name)
    return capped


def build_context(out: pd.DataFrame, as_of: pd.Timestamp, cfg: dict) -> RuleContext:
    """Read the resume config section (keys head_to_head and title_cycle) and the resume `out` frame once.
    Reuse the result across the stability draws: only the score order changes between draws."""
    h2h, tc = cfg["head_to_head"], cfg["title_cycle"]
    as_of = pd.Timestamp(as_of)
    max_gap = int(h2h["max_gap"])
    max_gap_recent = int(h2h.get("max_gap_recent") or max_gap)
    mode = str(h2h.get("ride_settled", "all")).lower()
    if mode not in ("all", "recent", "none"):
        raise ValueError(f"head_to_head.ride_settled must be all, recent or none, not {mode!r}")
    d = _decided(out)
    window = d[(as_of - d["date"]).dt.days <= float(h2h["max_years"]) * 365.25].sort_values(["date", "bout_id"])
    last_meeting: dict[tuple[str, str], tuple[pd.Timestamp, str]] = {}
    for x in window.itertuples():
        key = (x.fighter_a, x.fighter_b) if x.fighter_a <= x.fighter_b else (x.fighter_b, x.fighter_a)
        if (as_of - x.date).days > 365 and bool(getattr(x, "close", False)):
            last_meeting.pop(key, None)          # a close win more than a year old settles nothing
            continue
        last_meeting[key] = (x.date, x.fighter_a if x.result_a == 1.0 else x.fighter_b)
    beat_recently: dict[str, dict[str, pd.Timestamp]] = {}
    for x in d[(as_of - d["date"]).dt.days <= 365].itertuples():
        w, l = (x.fighter_a, x.fighter_b) if x.result_a == 1.0 else (x.fighter_b, x.fighter_a)
        prev = beat_recently.setdefault(w, {}).get(l)
        if prev is None or x.date > prev:
            beat_recently[w][l] = x.date
    return RuleContext(as_of, max_gap, max_gap_recent, int(tc["min_position"]), last_meeting,
                       negative_form(out), capped_fighters(out, as_of, tc), beat_recently, mode,
                       bool(tc.get("reserved_waives_h2h", True)))


def collect_constraints(order_by_score: Sequence[str], out: pd.DataFrame, as_of: pd.Timestamp, cfg: dict,
                        ctx: RuleContext | None = None) -> list[Constraint]:
    """Constraints for one division. `order_by_score` lists the contenders best first (no title holders).
    The head-to-head gap test uses this score order; the sequential rule tests the partially modified
    order, which is one source of its order dependence. Pass `ctx` (build_context) to skip the frame scans."""
    ctx = ctx or build_context(out, as_of, cfg)
    return _collect(list(order_by_score), ctx)


def _collect(order: list[str], ctx: RuleContext) -> list[Constraint]:
    pos = {f: i for i, f in enumerate(order)}
    cons: list[Constraint] = []
    for (f1, f2), (date, winner) in sorted(ctx.last_meeting.items()):
        if f1 not in pos or f2 not in pos or winner in ctx.negative_form:
            continue
        loser = f2 if winner == f1 else f1
        recent = (ctx.as_of - date).days <= 365
        gap = pos[winner] - pos[loser]
        if 0 < gap <= (ctx.max_gap_recent if recent else ctx.max_gap):
            cons.append(precedence(winner, loser, H2H, date))
        elif gap < 0 and (ctx.ride_settled == "all" or (ctx.ride_settled == "recent" and recent)):
            cons.append(ride(winner, loser, SETTLED, date))
    for c in order:
        if c in ctx.capped:
            cons.append(cap(c, ctx.min_position, TITLE_LOSS, ctx.capped[c]))
            for n, when in sorted(ctx.beat_recently.get(c, {}).items()):
                if n in pos and n != c:
                    cons.append(precedence(c, n, VICTIM, when, lift=False))
    return cons


def _when(c: Constraint) -> pd.Timestamp:
    return c.date if c.date is not None else pd.Timestamp.min


def _sort_key(c: Constraint) -> tuple:
    return (c.kind, c.fighter, c.other, _when(c).value, c.reason, c.min_position, c.lift)


def _reaches(succ: dict[str, set[str]], start: str, target: str) -> bool:
    seen, stack = {start}, [start]
    while stack:
        v = stack.pop()
        if v == target:
            return True
        for u in succ[v]:
            if u not in seen:
                seen.add(u)
                stack.append(u)
    return False


def _effective(order: list[str], lifts: dict[str, set[str]]) -> dict[str, int]:
    """Effective score position: the best among the fighter and everyone he is lifted over or rides with
    (a hold edge passes nothing up). Rides may form cycles, so relax to the unique fixed point."""
    prio = {f: i for i, f in enumerate(order)}
    changed = True
    while changed:
        changed = False
        for u in order:
            best = min((prio[v] for v in lifts.get(u, ())), default=prio[u])
            if best < prio[u]:
                prio[u] = best
                changed = True
    return prio


def solve(order_by_score: Sequence[str], constraints: Iterable[Constraint], waive: bool = True
          ) -> tuple[list[str], list[Constraint], list[Constraint]]:
    """Order the division to satisfy the constraints while staying as close as possible to the score order.

    Kahn's algorithm over the hard precedence edges; among the fighters whose predecessors are all placed,
    the heap picks the smallest (effective score position, score position). Positions below every cap are
    reserved: a capped fighter waits there. With `waive` (default), a fighter whose only unplaced
    predecessors are waiting capped fighters holding him through lift edges may take a reserved spot and
    those edges are waived, which is what the sequential title-cycle fill does ("the top slots go to
    fighters without a recent title-fight loss; fighters a capped fighter beat in the last year cannot
    jump over him either", so everyone else can). A hold edge (recent victim) is never waived.

    Returns (order, applied, dropped). `dropped` holds the precedence constraints removed to break cycles
    (always the oldest meeting in the cycle), the ones waived at a reserved spot, and any cap that could
    not hold because fewer than min_position - 1 eligible fighters exist; rides are soft and always count
    as applied. Constraints naming fighters outside `order_by_score` are ignored. The result depends only
    on the score order and the SET of constraints, not on the order they are listed in."""
    order = list(order_by_score)
    pos = {f: i for i, f in enumerate(order)}
    if len(pos) != len(order):
        raise ValueError("order_by_score contains a duplicate fighter")
    edges: dict[tuple[str, str], list[Constraint]] = {}
    caps: dict[str, list[Constraint]] = {}
    rides: list[Constraint] = []
    for c in constraints:
        if c.fighter not in pos or (c.kind != CAP and (c.other not in pos or c.other == c.fighter)):
            continue
        if c.kind == CAP:
            caps.setdefault(c.fighter, []).append(c)
        elif c.kind == PRECEDENCE:
            edges.setdefault((c.fighter, c.other), []).append(c)
        elif c.kind == RIDE:
            rides.append(c)
    # cycle breaking: add edges newest first; an edge that would close a cycle is the oldest in it
    succ: dict[str, set[str]] = {f: set() for f in order}
    lifts: dict[str, set[str]] = {f: set() for f in order}
    kept: dict[tuple[str, str], list[Constraint]] = {}
    dropped: list[Constraint] = []
    for (u, v), cs in sorted(edges.items(), key=lambda kv: (-max(_when(c) for c in kv[1]).value, kv[0])):
        if _reaches(succ, v, u):
            dropped.extend(cs)
        else:
            succ[u].add(v)
            kept[(u, v)] = cs
            if any(c.lift for c in cs):
                lifts[u].add(v)
    for c in rides:
        lifts[c.fighter].add(c.other)
    prio = _effective(order, lifts)
    first_allowed = {f: max(max(c.min_position for c in cs) - 1, 0) for f, cs in caps.items()}
    preds: dict[str, set[str]] = {f: set() for f in order}
    for u in order:
        for v in succ[u]:
            preds[v].add(u)
    heap = [(prio[f], pos[f], f) for f in order if not preds[f]]
    heapq.heapify(heap)
    result: list[str] = []
    placed: set[str] = set()

    def excluded(f: str, idx: int) -> bool:
        return f in first_allowed and idx < first_allowed[f]

    while len(result) < len(order):
        idx = len(result)
        held: list[tuple[int, int, str]] = []
        chosen = None
        while heap:
            item = heapq.heappop(heap)
            if excluded(item[2], idx):
                held.append(item)                 # the slot is reserved for fighters without a cap
                continue
            chosen = item
            break
        best_waiver = None
        if waive and any(excluded(f, idx) for f in order if f not in placed):
            # a fighter kept out only by waiting capped fighters' lift edges may take the reserved spot
            for f in order:
                if f in placed or not preds[f] or excluded(f, idx):
                    continue
                if all(excluded(u, idx) and all(c.lift for c in kept[(u, f)]) for u in preds[f]):
                    cand = (prio[f], pos[f], f)
                    if best_waiver is None or cand < best_waiver:
                        best_waiver = cand
        waived: list[tuple[str, str]] = []
        if best_waiver is not None and (chosen is None or best_waiver < chosen):
            if chosen is not None:
                held.append(chosen)               # back to the heap
            chosen = best_waiver
            waived = [(u, chosen[2]) for u in sorted(preds[chosen[2]])]
        if chosen is None:
            if not held:
                raise RuntimeError("precedence graph still has a cycle after breaking")
            chosen = held.pop(0)                  # nobody eligible is free: the cap is relaxed
        for item in held:
            heapq.heappush(heap, item)
        f = chosen[2]
        for u, v in waived:
            succ[u].discard(v)
            dropped.extend(kept.pop((u, v)))
        preds[f] = set()
        result.append(f)
        placed.add(f)
        for v in sorted(succ[f]):
            preds[v].discard(f)
            if not preds[v]:
                heapq.heappush(heap, (prio[v], pos[v], v))
    applied: list[Constraint] = list(rides)
    for cs in kept.values():
        applied.extend(cs)
    final = {f: i for i, f in enumerate(result)}
    for f, cs in caps.items():
        for c in cs:
            (applied if final[f] + 1 >= c.min_position else dropped).append(c)
    return result, sorted(applied, key=_sort_key), sorted(dropped, key=_sort_key)


def violations(order: Sequence[str], constraints: Iterable[Constraint]) -> list[Constraint]:
    """Hard constraints (PRECEDENCE, CAP) the given order breaks; fighters missing from `order` are skipped.
    Rides are soft and are reported by placement_report instead."""
    pos = {f: i for i, f in enumerate(order)}
    bad = []
    for c in constraints:
        if c.fighter not in pos:
            continue
        if c.kind == CAP and pos[c.fighter] + 1 < c.min_position:
            bad.append(c)
        elif c.kind == PRECEDENCE and c.other in pos and pos[c.fighter] > pos[c.other]:
            bad.append(c)
    return bad


def inverted_rides(order: Sequence[str], constraints: Iterable[Constraint]) -> list[Constraint]:
    """Settled results (RIDE) the given order inverts: the loser ended up above the winner."""
    pos = {f: i for i, f in enumerate(order)}
    return [c for c in constraints if c.kind == RIDE and c.fighter in pos and c.other in pos
            and pos[c.fighter] > pos[c.other]]


def placement_report(order_by_score: Sequence[str], final_order: Sequence[str],
                     applied: Iterable[Constraint] = (), dropped: Iterable[Constraint] = (),
                     division: str = "", top_n: int = 15) -> dict:
    """How far the final order sits from the score order: fighters moved, top-`top_n` spots whose occupant
    differs, max displacement, per-fighter moves, settled results inverted, and notes in the format the
    sequential rules print ("<div>: X moved above Y (won YYYY-MM-DD)", "<div>: X #a -> #b (reason)")."""
    score_pos = {f: i for i, f in enumerate(order_by_score)}
    final_pos = {f: i for i, f in enumerate(final_order)}
    if set(score_pos) != set(final_pos) or len(score_pos) != len(order_by_score):
        raise ValueError("final_order must hold the same fighters as order_by_score, each once")
    moves = [(f, score_pos[f] + 1, final_pos[f] + 1) for f in final_order if final_pos[f] != score_pos[f]]
    top_changed = sum(1 for i in range(min(top_n, len(final_order))) if final_order[i] != order_by_score[i])
    tag = f"{division}: " if division else ""
    applied, dropped = list(applied), list(dropped)
    notes = [f"{tag}{c.fighter} moved above {c.other} (won {c.date.date()})"
             for c in sorted((c for c in applied if c.kind == PRECEDENCE and c.reason == H2H
                              and score_pos.get(c.fighter, -1) > score_pos.get(c.other, -1)), key=_when)]
    for c in applied:
        f = c.fighter
        if c.kind == CAP and f in final_pos and final_pos[f] != score_pos[f]:
            notes.append(f"{tag}{f} #{score_pos[f] + 1} -> #{final_pos[f] + 1} (lost a title fight {c.date.date()}; "
                         "the champion fights someone else next)")
    seen = set()
    for c in applied:
        n = c.other
        if c.kind == PRECEDENCE and c.reason == VICTIM and n in final_pos and final_pos[n] > score_pos[n] and n not in seen:
            seen.add(n)
            notes.append(f"{tag}{n} #{score_pos[n] + 1} -> #{final_pos[n] + 1} (lost to a fighter held by the "
                         "title-cycle rule in the last year)")
    lifts: dict[str, set[str]] = {}
    for c in applied:
        if c.kind == RIDE or (c.kind == PRECEDENCE and c.lift):
            lifts.setdefault(c.fighter, set()).add(c.other)
    prio = _effective(list(order_by_score), lifts)
    for c in applied:
        w, l = c.fighter, c.other
        if c.kind == RIDE and final_pos[w] < final_pos[l] and prio[l] < score_pos[w]:
            notes.append(f"{tag}{w} kept above {l} (won {c.date.date()})")    # the ride carried the winner up
    inverted = inverted_rides(final_order, applied)
    for c in inverted:
        notes.append(f"{tag}{c.fighter} sits below {c.other} despite the win on {c.date.date()} (held by a harder rule)")
    cap_at = {c.fighter: c.min_position for c in applied + dropped if c.kind == CAP}
    for c in dropped:
        if c.kind == CAP:
            why = "too few eligible fighters for the reserved spots"
        elif c.fighter in cap_at and c.other in final_pos and final_pos[c.other] + 1 < cap_at[c.fighter]:
            why = f"waived, {c.other} took a reserved spot (#{final_pos[c.other] + 1}) over the capped {c.fighter}"
        else:
            why = "oldest meeting in a cycle"
        notes.append(f"{tag}dropped {c.describe()}: {why}")
    return {"division": division, "moved": len(moves), "top15_changed": top_changed,
            "max_displacement": max((abs(a - b) for _, a, b in moves), default=0), "moves": moves,
            "settled_inverted": [(c.fighter, c.other, c.date) for c in inverted], "notes": notes}


def apply_to_board(cont: pd.DataFrame, out: pd.DataFrame, as_of: pd.Timestamp, cfg: dict,
                   ctx: RuleContext | None = None) -> tuple[pd.DataFrame, list[str], dict]:
    """Drop-in for head_to_head() followed by title_cycle() in resume_board.build(): `cont` holds the scored
    contenders with columns division, fighter and pos (score order, 1-based per division); the frame comes
    back with pos replaced by the solved order, plus the notes and a report keyed by division."""
    ctx = ctx or build_context(out, as_of, cfg)
    notes: list[str] = []
    fixed: list[pd.DataFrame] = []
    divisions: dict[str, dict] = {}
    for div, g in cont.groupby("division"):
        order = list(g.sort_values("pos")["fighter"])
        cons = _collect(order, ctx)
        final, applied, dropped = solve(order, cons, waive=ctx.waive)
        rep = placement_report(order, final, applied, dropped, division=str(div))
        rep["constraints"] = cons
        rep["applied"] = applied
        rep["dropped"] = dropped
        divisions[str(div)] = rep
        notes += rep["notes"]
        fixed.append(pd.DataFrame({"division": div, "fighter": final, "pos": range(1, len(final) + 1)}))
    fixed = pd.concat(fixed) if fixed else pd.DataFrame({"division": [], "fighter": [], "pos": []})
    report = {"divisions": divisions,
              "moved": sum(r["moved"] for r in divisions.values()),
              "top15_changed": sum(r["top15_changed"] for r in divisions.values()),
              "max_displacement": max((r["max_displacement"] for r in divisions.values()), default=0),
              "constraints": sum(len(r["constraints"]) for r in divisions.values()),
              "settled_inverted": sum(len(r["settled_inverted"]) for r in divisions.values()),
              "dropped": [f"{d}: {c.describe()}" for d, r in divisions.items() for c in r["dropped"]]}
    return cont.drop(columns=["pos"]).merge(fixed, on=["division", "fighter"]), notes, report
