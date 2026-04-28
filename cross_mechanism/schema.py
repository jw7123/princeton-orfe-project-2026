"""
cross_mechanism/schema.py
=========================

The shared output schema every adapter writes to. Defines the contract
that decouples per-mechanism simulator implementation from downstream
comparison logic.

A row is one applicant. The schema is deliberately mechanism-agnostic
so that adding a fourth mechanism (e.g. a CTCAC `CA_9pct` adapter) does
not require any change to the harness.
"""

from __future__ import annotations

from typing import Dict, List, Set

# The twelve output columns, in canonical order. Adapters that emit a
# CSV must include exactly these columns; missing columns will cause
# the harness to reject the file with a clear error.
CROSS_MECHANISM_COLUMNS: List[str] = [
    "mechanism",            # str: one of KNOWN_MECHANISMS below
    "cycle_year",           # int: e.g. 2025
    "app_id",               # str: unique within (mechanism, cycle_year)
    "name",                 # str: human-readable project name
    "regional_pool",        # str: e.g. "Bay Area" (CA), "R7/Urban" (TX 9%), "" (TX 4%)
    "set_aside_flags",      # str: comma-separated tags (e.g. "USDA,Nonprofit")
    "score_or_priority",    # float: native to mechanism (see LOWER_IS_BETTER)
    "request_amount",       # float: dollars requested
    "predicted_award",      # float: dollars awarded by simulator (0 if none)
    "predicted_via",        # str: pool / step / route name
    "predicted_blocked_by", # str: reason for non-award
    "actual_award",         # float: ground-truth dollars awarded; NaN if unknown
]

# Mechanism labels that the harness expects to find in `mechanism`.
# Adding a new mechanism: append its label here.
KNOWN_MECHANISMS: Set[str] = {
    "CA_bond",     # California CDLAC bond / 4% LIHTC / state credit
    "CA_9pct",     # (placeholder) California CTCAC 9% competitive
    "TX_9pct",     # Texas 9% LIHTC competitive cycle
    "TX_4pct",     # Texas 4% / tax-exempt bond lottery + queue
}

# Mechanisms whose score_or_priority field is interpreted as
# "lower is better" (queue rank, reservation date as ordinal).
# All others are higher-is-better.
LOWER_IS_BETTER: Set[str] = {"TX_4pct"}

# Canonical values that may appear in `predicted_blocked_by`. The
# harness uses these for the per-mechanism blocker breakdown.
KNOWN_BLOCKERS: Dict[str, str] = {
    "":                       "awarded",
    "outcompeted":            "ranked below threshold within pool",
    "score_below_min":        "below mechanism's minimum score (CA: 89 pts)",
    "capacity_exhausted":     "queue cleared below this project's PD (TX 4%)",
    "applicant_cap":          "$6M aggregate cap (TX 9% §11.4(a))",
    "tract_dedup":            "one-award-per-urban-tract (TX 9% §11.3(g))",
    "terminal:withdrawn":     "BRB log: application withdrawn",
    "terminal:closed":        "BRB log: reservation closed without conversion",
}


def validate_schema(df) -> None:
    """Raise ValueError if df does not satisfy the schema."""
    missing = [c for c in CROSS_MECHANISM_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    bad_mech = set(df["mechanism"].dropna().unique()) - KNOWN_MECHANISMS
    if bad_mech:
        raise ValueError(f"Unknown mechanism labels: {bad_mech}")
