"""
sweep/sweep_runner.py
=====================

Inject each of the six synthetic project specifications from
`synthetic_specs.py` into each mechanism's 2025 pool and report whether
the spec is awarded.

Usage:
    python -m cross_mechanism.sweep.sweep_runner \\
        --tx9-workbook data/25261014HTC9pctAwardWaitingList.xlsx \\
        --out-dir out

This script handles the TX 9% leg directly via the simulator's
`build_synthetic`/`inject_and_run` API. The CA and TX 4% legs are
delegated to those simulators' own adapters and are not re-implemented
here; this module exists to fix the chat-08 known limitation that the
TX 9% column of `synthetic_sweep_by_spec.csv` was a stub.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

# Make the simulator importable regardless of how the script is invoked
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tx9_simulator as tx9
from cross_mechanism.sweep.synthetic_specs import SYNTHETIC_SPECS


def run_tx9_sweep(workbook_path: Path) -> pd.DataFrame:
    """Inject each spec into the TX 9% pool and report the per-spec outcome.

    Returns a DataFrame with one row per spec containing the relevant
    audit columns (region, score, predicted award, awarded_via, blocker).
    """
    real_apps = tx9.load_applications(workbook_path)

    rows: List[Dict[str, object]] = []
    for spec in SYNTHETIC_SPECS:
        tx9_kwargs = dict(spec["tx9"])
        # Build a fresh synthetic for THIS injection so the awarded/excluded
        # state from a prior run does not leak in.
        synth = tx9.build_synthetic(**tx9_kwargs, syn_id=f"SYN-{spec['spec_id']}")

        # inject_and_run resets awarded/excluded state on every app in the
        # combined pool, so it is safe to call repeatedly with the same
        # `real_apps` list.
        state, all_apps = tx9.inject_and_run(real_apps, [synth])

        # Find our synthetic in the returned pool
        match = next(a for a in all_apps if a.app_id == synth.app_id)
        rows.append({
            "spec_id":           spec["spec_id"],
            "mechanism":         "TX_9pct",
            "region":            tx9_kwargs["region"],
            "urban_rural":       tx9_kwargs["urban_rural"],
            "total_score":       tx9_kwargs["total_score"],
            "predicted_award":   bool(match.awarded),
            "awarded_via":       match.awarded_via,
            "excluded_by":       match.excluded_by,
        })

    df = pd.DataFrame(rows)
    return df


def update_sweep_table(tx9_df: pd.DataFrame, baseline_csv: Path,
                       out_csv: Path) -> pd.DataFrame:
    """Merge the new TX 9% column into the existing per-spec sweep CSV.

    The baseline CSV (chat-03 deliverable, archived in the project) has
    columns `spec_id, CA_bond, TX_4pct, TX_9pct` with TX 9% set to '?'.
    This function replaces the '?' values with 'Y' or 'N' from `tx9_df`.
    """
    base = pd.read_csv(baseline_csv)
    tx9_outcomes = {
        row["spec_id"]: ("Y" if row["predicted_award"] else "N")
        for _, row in tx9_df.iterrows()
    }
    base["TX_9pct"] = base["spec_id"].map(tx9_outcomes).fillna(base["TX_9pct"])
    base.to_csv(out_csv, index=False)
    return base


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tx9-workbook", type=Path, required=True,
                    help="Path to the TDHCA AWL workbook "
                         "(25261014HTC9pctAwardWaitingList.xlsx).")
    ap.add_argument("--baseline-csv", type=Path,
                    default=Path("synthetic_sweep_by_spec.csv"),
                    help="Existing per-spec sweep CSV to update "
                         "(TX 9% column will be overwritten).")
    ap.add_argument("--out-dir", type=Path, default=Path("out"),
                    help="Output directory for sweep_tx9.csv and the "
                         "updated synthetic_sweep_by_spec.csv.")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading TX 9% pool from {args.tx9_workbook} ...")
    tx9_df = run_tx9_sweep(args.tx9_workbook)
    tx9_csv = args.out_dir / "sweep_tx9.csv"
    tx9_df.to_csv(tx9_csv, index=False)
    print(f"Wrote {tx9_csv}")
    print()
    print("TX 9% per-spec outcomes:")
    print(tx9_df.to_string(index=False))
    print()

    if args.baseline_csv.exists():
        out_baseline = args.out_dir / "synthetic_sweep_by_spec.csv"
        merged = update_sweep_table(tx9_df, args.baseline_csv, out_baseline)
        print(f"Updated cross-mechanism sweep table at {out_baseline}:")
        print(merged.to_string(index=False))
    else:
        print(f"NOTE: Baseline CSV {args.baseline_csv} not found; "
              "skipping cross-mechanism table update.")


if __name__ == "__main__":
    main()
