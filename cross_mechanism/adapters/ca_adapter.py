"""
adapters/ca_adapter.py
======================

Translate the California 2025 cycle (CDLAC bond / 4% LIHTC) into the
cross-mechanism schema by reading the published applicant list and
the simulator-produced awards file, and joining on application number.

The simulator that produces `Awarded_Projects.xlsx` is `Code.py` in the
repo root. `Code.py` is a thin wrapper around an Excel workbook
(`CA Bond Scoring Simulator.xlsm`) that uses xlwings to read scoring
inputs from the workbook and write the awarded set back into the
workbook plus a separate `Awarded_Projects.xlsx`. The original CDLAC
bond simulator was developed against the published 2025 allocation
cycle in summer 2025; for the thesis the full cycle has already been
run, and `Awarded_Projects.xlsx` is checked in.

This adapter does NOT re-run `Code.py` (which requires xlwings, an
Excel install, and the workbook in a writable location). It treats
`Awarded_Projects.xlsx` as the simulator's output of record and joins
it to the applicant list to recover the full pool, including losers.

If you re-run `Code.py` on a different cycle or with different scoring
inputs, regenerate `Awarded_Projects.xlsx` first and then re-run this
adapter.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cross_mechanism.schema import CROSS_MECHANISM_COLUMNS, validate_schema


def _set_aside_flags(row: pd.Series) -> str:
    """Compose a comma-separated set-aside tag string from CDLAC columns."""
    flags = []
    for col, tag in [
        ("BIPOC PREQUALIFIED", "BIPOC"),
        ("HOMELESS",           "Homeless"),
        ("ELI/VLI",            "ELI/VLI"),
        ("RURAL",              "Rural"),
        ("MIP",                "MIP"),
        ("FARMWORKER",         "Farmworker"),
    ]:
        v = row.get(col)
        if v is None:
            continue
        s = str(v).strip().upper()
        if s in {"YES", "Y", "X", "TRUE", "1"}:
            flags.append(tag)
    return ",".join(flags)


def _bond_request(row: pd.Series) -> float:
    """Bond request in dollars; safe coercion."""
    v = row.get("BOND REQUEST")
    try:
        return float(v) if v is not None and pd.notna(v) else 0.0
    except (ValueError, TypeError):
        return 0.0


def to_schema(applicants: pd.DataFrame, awards: pd.DataFrame,
              cycle_year: int) -> pd.DataFrame:
    """Build the cross-mechanism schema from CA applicants + awards."""
    # Standardize join key
    applicants = applicants.copy()
    awards = awards.copy()
    applicants["APPLICATION NUMBER"] = applicants["APPLICATION NUMBER"].astype(str).str.strip()
    awards["APPLICATION NUMBER"] = awards["APPLICATION NUMBER"].astype(str).str.strip()

    award_keyset = set(awards["APPLICATION NUMBER"])
    award_lookup = awards.set_index("APPLICATION NUMBER").to_dict("index")

    rows = []
    for _, app in applicants.iterrows():
        app_id = app["APPLICATION NUMBER"]
        is_winner = app_id in award_keyset
        bond_req = _bond_request(app)
        try:
            score = float(app.get("CDLAC TOTAL POINTS")) if pd.notna(app.get("CDLAC TOTAL POINTS")) else float("nan")
        except (ValueError, TypeError):
            score = float("nan")

        # Winner-side metadata (FUNDED FROM is the pool that paid out)
        if is_winner:
            funded_from = str(award_lookup[app_id].get("FUNDED FROM", "") or "")
            predicted_via = funded_from
            predicted_award = bond_req
            blocked_by = ""
        else:
            predicted_via = ""
            predicted_award = 0.0
            # 89-pt minimum is the only hard CA blocker we can identify
            # without re-running the simulator
            blocked_by = "score_below_min" if (pd.notna(score) and score < 89) else "outcompeted"

        rows.append({
            "mechanism":            "CA_bond",
            "cycle_year":           cycle_year,
            "app_id":               app_id,
            "name":                 str(app.get("PROJECT NAME") or ""),
            "regional_pool":        str(app.get("CDLAC REGION") or ""),
            "set_aside_flags":      _set_aside_flags(app),
            "score_or_priority":    score,
            "request_amount":       bond_req,
            "predicted_award":      predicted_award,
            "predicted_via":        predicted_via,
            "predicted_blocked_by": blocked_by,
            "actual_award":         float("nan"),
        })

    return pd.DataFrame(rows, columns=CROSS_MECHANISM_COLUMNS)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--applicants", type=Path, required=True,
                    help="01_May_20_Applicant_List.xlsx")
    ap.add_argument("--applicant-sheet", default="05.20.2025 APPLICANTS",
                    help="Sheet name in the applicant workbook.")
    ap.add_argument("--awards", type=Path, required=True,
                    help="Awarded_Projects.xlsx (output of Code.py).")
    ap.add_argument("--awards-sheet", default="Award_List",
                    help="Sheet name in the awards workbook.")
    ap.add_argument("--cycle-year", type=int, default=2025)
    ap.add_argument("--out", type=Path, required=True,
                    help="Output CSV path.")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    apps = pd.read_excel(args.applicants, sheet_name=args.applicant_sheet, header=1)
    awards = pd.read_excel(args.awards, sheet_name=args.awards_sheet)

    df = to_schema(apps, awards, args.cycle_year)
    validate_schema(df)
    df.to_csv(args.out, index=False)
    n_funded = int((df["predicted_award"] > 0).sum())
    print(f"Wrote {len(df)} rows ({n_funded} funded) to {args.out}; schema OK.")


if __name__ == "__main__":
    main()
