# `cross_mechanism` — A Standardized Comparison Harness for LIHTC Allocation Mechanisms

> Companion code repository for:
> Williams, J. (2026). *Allocation Under Scarcity: A Cross-Mechanism Comparison
> of Low-Income Housing Tax Credit Allocation in California and Texas.* ORF 497 
> Project, Princeton University. Adv: Prof. A. Kornhauser.

This repository implements three independent simulators of 2025 Low-Income
Housing Tax Credit (LIHTC) allocation cycles and a standardized comparison
harness that reads only their CSV outputs:

| Mechanism label | What it simulates | Engine |
|---|---|---|
| `CA_bond`  | California CDLAC bond / 4% LIHTC / state credit competitive scoring | `Code.py` (Excel-driven via xlwings) |
| `TX_9pct`  | Texas 9% LIHTC competitive scoring (10 TAC ch. 11, §11.6 cascade) | `tx9_simulator.py` |
| `TX_4pct`  | Texas 4% LIHTC / tax-exempt bond lottery + FCFS queue | `texas_4pct_rules_engine_with_funding.py` |

The three simulators do not import from each other. What they share is an
output schema (`cross_mechanism/schema.py`, twelve columns documented below).
A separate script (`cross_mechanism/harness/compare.py`) reads only those
CSVs and produces all of the comparison tables and the consolidated report
used in chapter 5 of the project.

This design is deliberate: it isolates mechanism-level claims from
simulator-level implementation choices, and it makes it structurally easy
to add a fourth mechanism (e.g., a CTCAC `CA_9pct` adapter) without
touching anything downstream of its CSV output.

---

## Quick start

```bash
git clone https://github.com/jw7123/princeton-orfe-project-2026.git
cd princeton-orfe-project-2026

# Python 3.11+
pip install -r requirements.txt

# Place the data files (listed below) in ./data/, then:
bash scripts/reproduce_chapter5.sh
```

`reproduce_chapter5.sh` runs the three commands listed under
[Reproducing the chapter 5 numbers](#reproducing-the-chapter-5-numbers)
in sequence and writes outputs to `out/`.

---

## Repository layout

```
cross_mechanism/
├── __init__.py
├── schema.py                          # CROSS_MECHANISM_COLUMNS contract
├── adapters/
│   ├── __init__.py
│   ├── ca_adapter.py                  # CA applicants + Awarded_Projects.xlsx → ca_predictions.csv
│   ├── tx4_adapter.py                 # TX 4% workbook Funding_Output → tx4_predictions.csv
│   └── tx9_actuals_loader.py          # tx9_simulator.py --csv-out → tx9_actuals.csv
├── sweep/
│   ├── __init__.py
│   ├── synthetic_specs.py             # Six archetypal projects (TX 9% mappings)
│   └── sweep_runner.py                # Injects each spec into the TX 9% pool, updates sweep CSV
├── harness/
│   ├── __init__.py
│   └── compare.py                     # Reads CSVs → summary, blocker breakdown, report.md

# Top-level simulators (called by the adapters above)
Code.py                                # CA CDLAC simulator (Excel/xlwings driver)
tx9_simulator.py                       # TX 9% simulator (single-file, no Excel)
texas_4pct_rules_engine_with_funding.py # TX 4% rules engine

# Repo-level files
LICENSE                                # MIT
requirements.txt
scripts/reproduce_chapter5.sh
synthetic_sweep_by_spec.csv            # Baseline cross-mechanism sweep table (CA + TX 4% columns)

# Required data files (place in ./data/)
01_May_20_Applicant_List.xlsx                       # CA 2025 applicant pool
Awarded_Projects.xlsx                               # CA 2025 awards (Code.py output)
CA_Bond_Scoring_Simulator.xlsm                      # CA simulator workbook (only needed to re-run Code.py)
25261014HTC9pctAwardWaitingList.xlsx                # TX 9% AWL workbook
Texas_4pct_Bond_Simulator_with_Funding_Layer.xlsx   # TX 4% workbook with populated Funding_Output sheet
```

---

## The standardized output schema

Every adapter writes its output in this twelve-column schema. This is the
single contract every downstream tool depends on.

| Column                  | Type   | Notes                                                                 |
|-------------------------|--------|-----------------------------------------------------------------------|
| `mechanism`             | str    | `CA_bond`, `CA_9pct`, `TX_9pct`, `TX_4pct`                            |
| `cycle_year`            | int    | calendar year of cycle (e.g. 2025)                                    |
| `app_id`                | str    | unique within mechanism + cycle                                       |
| `name`                  | str    | human-readable project name                                           |
| `regional_pool`         | str    | e.g. CA "Bay Area"; TX 9% "Region 7/Urban"; empty for TX 4%           |
| `set_aside_flags`       | str    | comma-separated set-aside tags                                        |
| `score_or_priority`     | float  | mechanism-specific; see `LOWER_IS_BETTER` registry in `schema.py`      |
| `request_amount`        | float  | $ requested                                                           |
| `predicted_award`       | float  | $ awarded by simulator (0 if none)                                    |
| `predicted_via`         | str    | pool / step / route name                                              |
| `predicted_blocked_by`  | str    | reason for non-award                                                  |
| `actual_award`          | float  | ground-truth $ awarded; NaN if not yet populated                      |

Two columns deserve comment.

**`score_or_priority` direction differs by mechanism.** Higher is better
for CA (CDLAC TOTAL POINTS) and TX 9% (Total Score). Lower is better
for TX 4% (simulated queue rank). A registry in `schema.py`
(`LOWER_IS_BETTER = {"TX_4pct"}`) tells the harness which way to invert
when computing percentile-style comparisons.

**`predicted_blocked_by` takes a small set of values.** `outcompeted`
(CA, TX 9% standard), `score_below_min` (CA, below the 89-point
threshold), `capacity_exhausted` (TX 4%, queue cleared below this
project's reservation date), `applicant_cap` (TX 9% §11.4(a) $6M cap),
`tract_dedup` (TX 9% §11.3(g) one-award-per-urban-tract), or
`terminal:withdrawn|closed` (TX 4%, application status data from the
BRB log indicated the reservation did not convert).

---

## Reproducing the chapter 5 numbers

From the repository root, with data files in `./data/`:

```bash
# 1. Per-mechanism predictions for the 2025 cycle
python -m cross_mechanism.adapters.ca_adapter \
    --applicants data/01_May_20_Applicant_List.xlsx \
    --applicant-sheet "05.20.2025 APPLICANTS" \
    --awards data/Awarded_Projects.xlsx \
    --cycle-year 2025 \
    --out out/ca_predictions.csv

python -m cross_mechanism.adapters.tx4_adapter \
    --workbook data/Texas_4pct_Bond_Simulator_with_Funding_Layer.xlsx \
    --cycle-year 2025 \
    --out out/tx4_predictions.csv

python -m cross_mechanism.adapters.tx9_actuals_loader \
    --waitlist data/25261014HTC9pctAwardWaitingList.xlsx \
    --cycle-year 2025 \
    --out out/tx9_actuals.csv

# 2. Synthetic-project sweep (six specs into the TX 9% pool)
python -m cross_mechanism.sweep.sweep_runner \
    --tx9-workbook data/25261014HTC9pctAwardWaitingList.xlsx \
    --baseline-csv synthetic_sweep_by_spec.csv \
    --out-dir out

# 3. Comparison harness: reads only CSVs, writes tables and report
python -m cross_mechanism.harness.compare \
    --predictions-dir out \
    --sweep-dir out \
    --out-dir out
```

Expected outputs in `out/`:

```
ca_predictions.csv             # 129 rows, 50 awards
tx4_predictions.csv            # 91 rows, 11 awards (under $300M assumed cap)
tx9_actuals.csv                # 85 rows, 65–68 awards depending on tie-break
sweep_tx9.csv                  # six TX 9% sweep rows (Y/N per spec)
synthetic_sweep_by_spec.csv    # cross-mechanism sweep table (Table 5.4)
summary_table.csv              # paper Table 5.1
blocker_breakdown.csv          # paper Table 5.2
report.md                      # auto-generated combined report
```

---

## Validation

| Mechanism | Pool size | Predicted awards | Recall vs published | Notes |
|---|---|---|---|---|
| `CA_bond` | 129 | 50 | **50/50 exact** | matches `Awarded_Projects.xlsx`; identical `FUNDED FROM` pool on every project |
| `TX_9pct` | 85 | 65 | **57/65 = 87.7%** | tie-break Monte Carlo bounds recall to 84.6%–95.4% |
| `TX_4pct` | 91 | 11 | n/a | queue-driven; 12.1% acceptance under $300M assumed pipeline cap |

The TX 9% simulator's tie-break sensitivity analysis is built in:

```bash
python tx9_simulator.py data/25261014HTC9pctAwardWaitingList.xlsx --sensitivity
```

The TX 4% adapter uses reservation date as the only queue key, with
lottery number breaking ties within the initial 10/10/2024 cohort. The
`Funding_Output` sheet of the workbook holds 91 historical 2025-cycle
projects (one row had no `tdhca_number` and is skipped). Funding cap is
modeled as $300M of post-lottery reservation volume.

---

## Adding a fourth mechanism

The repository is structured to absorb additional mechanisms without
touching the harness or any existing simulator. The natural extension
is a CTCAC adapter for California's 9% competitive LIHTC round (mechanism
label `CA_9pct`); the procedure below is generic.

1. **Write a simulator.** Self-contained module, takes raw inputs,
   produces a DataFrame of predictions. Don't import from the other
   simulators.
2. **Write an adapter.** Wraps the simulator's output into the twelve-
   column CSV schema documented above. Drop in `cross_mechanism/adapters/`.
3. **Register the mechanism label.** Edit `cross_mechanism/schema.py` to
   add the new mechanism string to `KNOWN_MECHANISMS` and, if it is
   lower-is-better (queue-rank style), to the `LOWER_IS_BETTER` set.
4. **Add to the sweep runner.** In `cross_mechanism/sweep/sweep_runner.py`,
   add a function analogous to `run_tx9_sweep` that injects each
   synthetic spec into the new mechanism's pool and writes
   `out/sweep_<mechanism>.csv`.
5. **(Optional) Add to the reproduction script.** Edit
   `scripts/reproduce_chapter5.sh` to call the new adapter.

The harness reads any file in `--predictions-dir` matching `*_predictions.csv`
or `*_actuals.csv`. A new mechanism shows up in the comparison
automatically.

---

## Known limitations

These are the simplifications and gaps flagged in the project text. They
are real and worth being honest about.

1. **No `CA_9pct` (CTCAC) mechanism.** The current CA simulator covers
   CDLAC bonds + 4% LIHTC + state credit (`CA_bond`). A separate CTCAC
   competitive-9% adapter is the natural next step; see [Adding a fourth
   mechanism](#adding-a-fourth-mechanism).
2. **CA actual_award column is NaN.** The CA adapter leaves
   `actual_award` empty because the CA simulator's predicted output
   was treated as ground truth in the original validation pass: 50/50
   exact match on the 2025 cycle, with identical `FUNDED FROM` pool on
   every project. For honest validation reporting against an
   independent ground truth, populate `actual_award` from a separate
   CDLAC award-decisions CSV.
3. **TX 4% pipeline cap is a model assumption.** The $300M post-lottery
   pipeline cap is a single-year stylized value; the real figure varies
   year to year with carryforward authority, P0 supplemental allocation,
   and BRB administrative discretion.
4. **TX 9% tie-breaker simplification.** The §11.7 cascade depends on
   per-feature proximity measurements not in any public dataset; the
   simulator uses TDHCA's published `Amenities Tie-Breaker Total` as a
   summary proxy. Run with `--sensitivity` to bound the resulting
   uncertainty.
5. **Award-unit non-comparability.** CA bond / TX 4% awards are bond
   face value; TX 9% awards are annual federal tax credit. The two are
   not directly comparable; the report flags this throughout.

---

## How to cite

If you use this code in academic work, please cite the project:

```bibtex
@misc{williams_simulators_2026,
  author = {Williams, Jim},
  title  = {{cross\_mechanism}: A standardized comparison harness for the
            California CDLAC, Texas 9\%, and Texas 4\% LIHTC allocation
            mechanisms},
  year   = {2026},
  howpublished = {Software repository},
  url    = {https://github.com/jw7123/princeton-orfe-project-2026}
}

@misc{williams_project_2026,
  author = {Williams, Jim},
  title  = {Allocation Under Scarcity: A Cross-Mechanism Comparison of
            Low-Income Housing Tax Credit Allocation in California and Texas},
  year   = {2026},
  school = {Princeton University},
  type   = {ORF 497 Senior Independent Work}
}
```

---

## License

MIT (see `LICENSE`).

---

## Acknowledgments

Advisor: Prof. Alain Kornhauser, Department of Operations Research and
Financial Engineering, Princeton University.

Data sources: Texas Department of Housing and Community Affairs (2025
QAP, AWL workbook, 4% process manual); California Debt Limit Allocation
Committee (2025 regulations); HUD Office of Policy Development and
Research (FY2025 MTSP income limits, LIHTC database).

The original CA CDLAC bond simulator (`Code.py`) was developed against
CDLAC's published 2025 allocation cycle in summer 2025; the
cross-mechanism comparison framework was developed for the senior project
in spring 2026.
