"""
experiments.py - The experiment register: every test, pilot and candidate comparison, kept for reference.

    experiments/register.jsonl        one JSON object per experiment (machine-readable, append-only)
    experiments/results/<id>/         the small result files each entry points to (JSON, CSV)
    experiments/REGISTER.md           rendered from register.jsonl by `python -m mmalab.experiments`

Why: rules get re-tried when nobody can find the last result. An entry records the question, the exact method
(data window, bouts, metric, baseline), the candidate's parameters, the numbers with intervals, the
face-validity check, and the decision with its reason, so a rejected idea is as findable as an adopted one.

    from mmalab.experiments import record
    record(exp_id="EXP-2026-10-20-09", title=..., question=..., method=..., candidate=..., results=...,
           face_validity=..., decision="rejected", reason=..., files={"summary.json": obj_or_path})
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments"
REGISTER = EXP / "register.jsonl"
RESULTS = EXP / "results"

DECISIONS = ("adopted", "rejected", "parked", "running", "superseded", "informational")


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def next_id(date: str | None = None) -> str:
    """EXP-YYYY-MM-DD-nn, nn counting within the day."""
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = sum(1 for e in load() if e["id"].startswith(f"EXP-{date}-"))
    return f"EXP-{date}-{n + 1:02d}"


def load() -> list[dict]:
    if not REGISTER.exists():
        return []
    return [json.loads(line) for line in REGISTER.read_text().splitlines() if line.strip()]


def record(exp_id: str | None, title: str, question: str, method: dict | str, candidate: dict | str,
           results: dict | str, decision: str, reason: str, face_validity: dict | str | None = None,
           files: dict | None = None, date: str | None = None, commit: str | None = None, notes: str | None = None) -> dict:
    """Append one experiment. `files` maps a file name to a path to copy or an object to dump as JSON; they land in
    experiments/results/<id>/. Returns the entry."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
    exp_id = exp_id or next_id(date)
    if any(e["id"] == exp_id for e in load()):
        raise ValueError(f"{exp_id} already registered; use update() or a new id")
    stored = []
    if files:
        d = RESULTS / exp_id
        d.mkdir(parents=True, exist_ok=True)
        for name, src in files.items():
            dst = d / name
            if isinstance(src, (str, Path)) and Path(src).exists():
                if Path(src).resolve() != dst.resolve():
                    shutil.copyfile(src, dst)
            else:
                dst.write_text(json.dumps(src, indent=1, default=str))
            stored.append(str(dst.relative_to(ROOT)))
    entry = {"id": exp_id, "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"), "title": title,
             "question": question, "method": method, "candidate": candidate, "results": results,
             "face_validity": face_validity, "decision": decision, "reason": reason, "files": stored,
             "commit": commit or _commit(), "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}
    if notes:
        entry["notes"] = notes
    EXP.mkdir(exist_ok=True)
    with REGISTER.open("a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    render()
    return entry


def update(exp_id: str, **fields) -> dict:
    """Change fields of an existing entry (for example decision: running -> rejected once the result is in)."""
    entries = load()
    hit = [e for e in entries if e["id"] == exp_id]
    if not hit:
        raise KeyError(exp_id)
    e = hit[0]
    if "decision" in fields and fields["decision"] not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    files = fields.pop("files", None)
    if files:
        d = RESULTS / exp_id
        d.mkdir(parents=True, exist_ok=True)
        for name, src in files.items():
            dst = d / name
            if isinstance(src, (str, Path)) and Path(src).exists():
                if Path(src).resolve() != dst.resolve():
                    shutil.copyfile(src, dst)
            else:
                dst.write_text(json.dumps(src, indent=1, default=str))
            rel = str(dst.relative_to(ROOT))
            if rel not in e["files"]:
                e["files"].append(rel)
    e.update(fields)
    e["updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    REGISTER.write_text("".join(json.dumps(x, default=str) + "\n" for x in entries))
    render()
    return e


def _fmt(v) -> str:
    if isinstance(v, dict):
        return "<br>".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(_fmt(x) for x in v)
    return str(v)


def render() -> Path:
    entries = load()
    lines = ["# Experiment register", "",
             "Every test, pilot and candidate comparison run on REAL, in order. Rendered from `experiments/register.jsonl` by "
             "`python -m mmalab.experiments`; edit the JSONL (or call `mmalab.experiments.record`), not this file. "
             "The protocol and the entry template are in `experiments/README.md`.", "",
             "| ID | Date | Title | Decision |", "|---|---|---|---|"]
    for e in entries:
        lines.append(f"| [{e['id']}](#{e['id'].lower()}) | {e['date']} | {e['title']} | {e['decision']} |")
    lines.append("")
    for e in entries:
        lines += [f"## {e['id']}", "", f"{e['title']}  ", f"Date {e['date']}, decision: {e['decision']}, code at commit `{e['commit']}`.", "",
                  f"Question. {e['question']}", ""]
        if isinstance(e["method"], dict):
            lines += ["| Method | |", "|---|---|"] + [f"| {k} | {_fmt(v)} |" for k, v in e["method"].items()] + [""]
        else:
            lines += ["Method. " + str(e["method"]), ""]
        lines += ["Candidate. " + (e["candidate"] if isinstance(e["candidate"], str) else "`" + json.dumps(e["candidate"]) + "`"), ""]
        if isinstance(e["results"], dict):
            lines += ["| Result | |", "|---|---|"] + [f"| {k} | {_fmt(v)} |" for k, v in e["results"].items()] + [""]
        else:
            lines += ["Results. " + str(e["results"]), ""]
        if e.get("face_validity"):
            fv = e["face_validity"]
            if isinstance(fv, dict):
                lines += ["| Face validity | |", "|---|---|"] + [f"| {k} | {_fmt(v)} |" for k, v in fv.items()] + [""]
            else:
                lines += ["Face validity. " + str(fv), ""]
        lines += [f"Decision. {e['decision']}: {e['reason']}", ""]
        if e.get("notes"):
            lines += [f"Notes. {e['notes']}", ""]
        if e.get("files"):
            lines += ["Files: " + ", ".join(f"`{f}`" for f in e["files"]), ""]
    EXP.mkdir(exist_ok=True)
    out = EXP / "REGISTER.md"
    out.write_text("\n".join(lines))
    return out


if __name__ == "__main__":
    print(render(), f"({len(load())} entries)")
