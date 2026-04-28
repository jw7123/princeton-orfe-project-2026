#!/usr/bin/env bash
# scripts/reproduce_chapter5.sh
# -----------------------------
# Run the full pipeline that produces the per-mechanism predictions, the
# synthetic-project sweep, and the comparison harness output used in
# chapter 5 of the thesis.
#
# Assumes the data files listed in README.md are placed in ./data/.
# All outputs land in ./out/.

set -euo pipefail

mkdir -p out

echo ">>> Step 1: Per-mechanism predictions for the 2025 cycle"

# CA: read the published applicants and the simulator's awards file.
# (This adapter does NOT re-run Code.py; treat Awarded_Projects.xlsx as
# the simulator's output of record.)
python -m cross_mechanism.adapters.ca_adapter \
    --applicants data/01_May_20_Applicant_List.xlsx \
    --applicant-sheet "05.20.2025 APPLICANTS" \
    --awards data/Awarded_Projects.xlsx \
    --awards-sheet "Award_List" \
    --cycle-year 2025 \
    --out out/ca_predictions.csv

# TX 4%: read the populated Funding_Output sheet of the workbook.
python -m cross_mechanism.adapters.tx4_adapter \
    --workbook data/Texas_4pct_Bond_Simulator_with_Funding_Layer.xlsx \
    --cycle-year 2025 \
    --out out/tx4_predictions.csv

# TX 9%: run the simulator's --csv-out mode against the AWL workbook.
python -m cross_mechanism.adapters.tx9_actuals_loader \
    --waitlist data/25261014HTC9pctAwardWaitingList.xlsx \
    --cycle-year 2025 \
    --out out/tx9_actuals.csv

echo ""
echo ">>> Step 2: Synthetic-project sweep (six specs x TX 9%)"
# This populates the TX 9% column of synthetic_sweep_by_spec.csv. The
# CA and TX 4% columns of that file are produced by the per-mechanism
# adapters and were checked in alongside the chat-03 deliverable; the
# sweep runner only fills in the TX 9% column.
python -m cross_mechanism.sweep.sweep_runner \
    --tx9-workbook data/25261014HTC9pctAwardWaitingList.xlsx \
    --baseline-csv synthetic_sweep_by_spec.csv \
    --out-dir out

echo ""
echo ">>> Step 3: Comparison harness (reads CSVs, writes summary tables + report)"
python -m cross_mechanism.harness.compare \
    --predictions-dir out \
    --sweep-dir out \
    --out-dir out

echo ""
echo "Done. See out/report.md for the consolidated report."
