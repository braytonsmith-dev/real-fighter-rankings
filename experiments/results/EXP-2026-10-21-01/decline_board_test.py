"""Archived as run on 2026-10-21 (paths generalised: <repo> is the checkout, <scratch dir> a working directory).
Board-level test of the decline index: adjust the resume rating on every panel board by the index components
(population age curve, individual level and slope, both) in rating points, and score the panel concordance and log
loss against the unadjusted v1.0 and B+0 rules. Every as-of index uses bouts before the board date only; the
hyperparameters follow the walk-forward choices (default before 2017)."""
import json, sys, time
sys.path.insert(0, "<repo>/src")
import numpy as np, pandas as pd
from mmalab import board_tune as bt, decline as dc

OUTD = "<scratch dir>"
PROC = "<repo>/data/processed"
t0 = time.time()
panel = bt.load_or_build_panel({})
F, E = panel.F, panel.E
print("panel", len(panel.dates), "dates", len(F), "rows", len(E), "bouts", round(time.time() - t0, 1), "s", flush=True)

bouts = pd.read_csv(f"{PROC}/bouts_with_stats.csv", parse_dates=["date"])
rated = pd.read_csv(f"{PROC}/bouts_rated.csv", parse_dates=["date"])
fighters = pd.read_csv(f"{PROC}/fighters.csv")
t = dc.residual_table(bouts, rated, fighters, rating="resume")
rep = json.load(open("<repo>/outputs/decline_report_research_resume_perf.json"))
hp_by_year = {row["year"]: {k: row[k] for k in dc.DEFAULT_HP} for row in rep["hyperparameters_by_year"]}

pop = np.zeros(len(F)); ind = np.zeros(len(F)); lvl = np.zeros(len(F))
for di, idx in F.groupby("di").indices.items():
    d = pd.Timestamp(panel.dates[di])
    hp = hp_by_year.get(d.year, dc.DEFAULT_HP)
    ix = dc.index_as_of(t, d, hp).set_index("fighter")
    names = F["fighter"].to_numpy()[idx]
    pop[idx] = ix["population_expectation"].reindex(names).fillna(0.0).to_numpy()
    ind[idx] = ix["individual_prediction"].reindex(names).fillna(0.0).to_numpy()
    lvl[idx] = ix["individual_level"].reindex(names).fillna(0.0).to_numpy()
    if di % 50 == 0:
        print("as-of", d.date(), "covered", int(ix.index.isin(names).sum()), "of", len(names), round(time.time() - t0, 1), "s", flush=True)
F["_pop"], F["_ind"], F["_lvl"] = pop, ind, lvl
print("index coverage of board rows:", round(float((F["_ind"] != 0).mean()), 3), flush=True)

base_rating = F["rating"].to_numpy(dtype=float).copy()
years = E["year"].to_numpy()
ev = (E["event"].astype(str) + "|" + E["date"].dt.strftime("%Y-%m-%d")).to_numpy()


def run(p: dict, adjust: np.ndarray, label: str) -> tuple[dict, dict]:
    F["rating"] = base_rating + adjust
    panel._age_cache = {}
    res, det = bt.evaluate(panel, bt.score_panel(panel, p))
    F["rating"] = base_rating
    panel._age_cache = {}
    return res, det


rows, dets = [], {}
K = dc.POINTS_PER_RESIDUAL
for rules, p in (("v1.0", bt.v10_params()), ("B+0", bt.bplus0_params())):
    variants = {
        "unadjusted": np.zeros(len(F)),
        "age discount 33/20 (EXP-09 style)": None,
        "population curve x1": K * pop, "population curve x0.5": 0.5 * K * pop,
        "individual (level+slope) x1": K * ind, "individual x0.5": 0.5 * K * ind, "individual level only x1": K * lvl,
        "population + individual x1": K * (pop + ind), "population + individual x0.5": 0.5 * K * (pop + ind),
    }
    for name, adj in variants.items():
        if adj is None:
            res, det = run({**p, "age_discount": {"from_age": 33, "points_per_year": 20}}, np.zeros(len(F)), name)
        else:
            res, det = run(p, adj, name)
        dets[(rules, name)] = det
        row = {"rules": rules, "variant": name, "bouts": res["bouts"], "concordance": round(res["concordance"], 4), "log_loss": round(res["log_loss"], 4),
               "top15_conc": round(res["top15"]["concordance"], 4), "top30_conc": round(res["top30"]["concordance"], 4)}
        if name != "unadjusted":
            b = dets[(rules, "unadjusted")]
            bs_c = bt.event_block_bootstrap(det["conc"], b["conc"], ev)
            bs_l = bt.event_block_bootstrap(det["ll"], b["ll"], ev)
            row["d_conc"] = round(float(np.mean(det["conc"] - b["conc"])), 4); row["d_conc_ci"] = [round(x, 4) for x in bs_c["ci95"]]
            row["d_ll"] = round(float(np.mean(det["ll"] - b["ll"])), 4); row["d_ll_ci"] = [round(x, 4) for x in bs_l["ci95"]]
            m2017 = years >= 2017
            row["d_conc_2017+"] = round(float(np.mean((det["conc"] - b["conc"])[m2017])), 4)
        rows.append(row)
        print(json.dumps(row), flush=True)
pd.DataFrame(rows).to_csv(f"{OUTD}/decline_board_test.csv", index=False)
print("DONE", round(time.time() - t0, 1), "s")
