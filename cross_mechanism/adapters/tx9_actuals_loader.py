"""
adapters/tx9_actuals_loader.py
==============================

Wraps `tx9_simulator.py` to produce a CSV in the cross-mechanism schema
format. The simulator already has a `--csv-out` mode that writes the
schema directly; this adapter is mostly a thin pass-through with input
validation and a sanity check on the output schema.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cross_mechanism.schema import validate_schema


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--waitlist", type=Path, required=True,
                    help="TDHCA AWL workbook (xlsx).")
    ap.add_argument("--cycle-year", type=int, default=2025)
    ap.add_argument("--out", type=Path, required=True,
                    help="Output CSV path.")
    args = ap.parse_args()

    if not args.waitlist.exists():
        raise FileNotFoundError(args.waitlist)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    sim_script = ROOT / "tx9_simulator.py"
    cmd = [sys.executable, str(sim_script), str(args.waitlist),
           "--csv-out", str(args.out)]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    df = pd.read_csv(args.out)
    if "cycle_year" not in df.columns or df["cycle_year"].isna().all():
        df["cycle_year"] = args.cycle_year
        df.to_csv(args.out, index=False)
    validate_schema(df)
    print(f"Wrote {len(df)} rows to {args.out}; schema OK.")


if __name__ == "__main__":
    main()
