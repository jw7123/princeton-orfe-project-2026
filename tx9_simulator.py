"""
Texas 9% Competitive Housing Tax Credit (HTC) Allocation Simulator
===================================================================

Implements the §11.6 allocation algorithm from the 2025 Texas Qualified
Allocation Plan (10 TAC Chapter 11) and validates against the published
2025 Award and Waiting List recommendations.

Author: Jim Williams (ORF 497, Princeton University, 2026)
Advisor: Prof. Alain Kornhauser

Modeled rules
-------------
- §11.6(b)(3)(A) USDA Set-Aside (Step 1)
- §11.6(b)(3)(B) At-Risk Set-Aside, with USDA spillover (Step 2)
- §11.6(b)(3)(C) Initial Subregion Selection (Step 3)
- §11.6(b)(3)(D) Rural Regional Collapse (Step 4)
- §11.6(b)(3)(E) Statewide Collapse (Step 5)
- §11.6(b)(3)(F) Contingent Qualified Nonprofit Set-Aside (Step 6)
- §11.7 tie-breaker cascade (USDA TB, then Amenities TB summary)
- §11.4(a) $6M aggregate per-applicant cap (proxy: Primary Contact)
- §11.3(g) one-award-per-census-tract in urban subregions

Modeled simplifications (flagged in paper methodology)
------------------------------------------------------
- §11.7 cascade resolved using AWL "Amenities Tie-Breaker Total" summary;
  per-feature proximity (park, school, sum-of-distances within 100 ft,
  linear distance to nearest LIHTC dev with same target population) is
  not in public data. This is the dominant residual error source.
- Total Score taken as agency-final from the AWL workbook, not re-derived
  from §11.9 primitives. §11.9(d)(1)(4)(5)(6)(7) involve agency-determined
  adjustments (local govt letters, QCP, state rep letters, community
  input, CRP) that are not predictable from project attributes alone.
- §11.4(a) cap uses Primary Contact as a proxy for "Applicant /
  Developer / Affiliate"; full entity resolution would require Affiliate
  disclosure data not in the AWL workbook.
- §11.6(b)(3)(C)(i)–(v) intra-subregion priorities (rural rescue,
  Supportive Housing, rehab without HUD/USDA-RD subsidy, HQ Pre-K,
  Income Levels of Residents) only kick in when budget is tight; v1.5
  uses straight Total-Score ordering with §11.7 tie-breakers.

Inputs
------
- 25261014HTC9pctAwardWaitingList.xlsx (TDHCA AWL workbook)
- Funding constants (FY2025) from the "DRAFT 2025 STATE OF TEXAS
  COMPETITIVE HOUSING TAX CREDIT ESTIMATED ALLOCATION" table
  (December 1, 2024 version, published with the QAP).

CLI
---
    python tx9_simulator.py <wb>                       # validate
    python tx9_simulator.py <wb> --csv-out preds.csv   # cross-mech CSV
    python tx9_simulator.py <wb> --synthetic spec.json # inject synthetic
    python tx9_simulator.py <wb> --ablation            # rule contributions
    python tx9_simulator.py <wb> --sensitivity         # tie-break MC

Validation result (2025 cycle, default settings)
------------------------------------------------
85 apps, 65 actual TDHCA awards, 65 sim-predicted awards
- True positives:  57
- False positives: 11
- False negatives: 8
- Award recall:    87.7% (Monte Carlo tie-break range: 84.6%–95.4%)
- Award precision: 83.8%
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# FUNDING CONSTANTS — 2025 Texas 9% HTC ceiling
# ---------------------------------------------------------------------------
# Source: "DRAFT 2025 STATE OF TEXAS COMPETITIVE HOUSING TAX CREDIT
# ESTIMATED ALLOCATION, AND SUB-REGIONAL REQUEST AND ELDERLY FUNDING LIMITS"
# (TDHCA, December 1, 2024). Final Funding Amount column.
#
# Subregion code = (region_int, "Urban" | "Rural").
# Values are the per-subregion ceiling AFTER the >$750k Rural floor
# rebalancing has already been applied.

SUBREGION_CEILINGS: Dict[Tuple[int, str], float] = {
    # Urban subregions
    (1,  "Urban"): 1_366_814.08,
    (2,  "Urban"):   759_354.55,
    (3,  "Urban"): 17_163_032.94,
    (4,  "Urban"): 1_196_472.90,
    (5,  "Urban"): 1_107_877.28,
    (6,  "Urban"): 16_835_689.04,
    (7,  "Urban"): 5_990_205.46,
    (8,  "Urban"): 3_060_073.47,
    (9,  "Urban"): 6_600_743.60,
    (10, "Urban"): 1_298_739.75,
    (11, "Urban"): 6_541_843.30,
    (12, "Urban"): 1_109_840.22,
    (13, "Urban"): 3_043_063.59,
    # Rural subregions
    (1,  "Rural"):   777_283.02,
    (2,  "Rural"):   750_000.00,
    (3,  "Rural"):   769_410.04,
    (4,  "Rural"): 1_704_693.55,
    (5,  "Rural"): 1_202_557.17,
    (6,  "Rural"):   750_000.00,
    (7,  "Rural"):   750_000.00,
    (8,  "Rural"):   750_000.00,
    (9,  "Rural"):   750_000.00,
    (10, "Rural"):   838_907.34,
    (11, "Rural"): 1_166_816.26,
    (12, "Rural"):   750_000.00,
    (13, "Rural"):   750_000.00,
}

# Statewide set-asides (carved from the grand total, not from subregion pools)
AT_RISK_POOL  = 13_726_485.00   # 15% of $91,509,903
USDA_POOL     =  4_575_495.00   # 5% of total, drawn FROM At-Risk pool
NONPROFIT_MIN =  9_150_990.30   # 10% statutory minimum (§42)

# Per-application max request (upper bound across all subregions)
MAX_REQUEST_CAP = 2_000_000.00


# ---------------------------------------------------------------------------
# DATA LOADER
# ---------------------------------------------------------------------------

@dataclass
class Application:
    """One 9% HTC application as represented in the AWL workbook."""
    app_id: str
    name: str
    city: str
    region: int                 # 1-13
    urban_rural: str            # "Urban" or "Rural"
    at_risk: bool
    usda: bool
    nonprofit: bool
    construction_type: str
    total_units: int
    target_population: str      # "General", "Elderly", "Supportive Housing", etc.
    htc_request: float          # dollars requested
    self_score: float
    total_score: float          # AGENCY-FINAL score (this is what we use)
    tb_usda: float              # §11.7(1) USDA tie-breaker
    tb_amenities: float         # §11.7(2) amenities tie-breaker
    actual_recommendation: str  # ground truth: "Award" / "Credit Return" / "" (waiting)
    primary_contact: str = ""   # for §11.4(a) $6M per-applicant cap
    census_tract: str = ""      # for §11.3(g) one-award-per-tract rule

    # Filled in by the simulator
    awarded: bool = False
    awarded_via: str = ""       # "USDA SA" / "AtRisk SA" / "Subregion" / etc.
    excluded_by: str = ""       # blocked-by reason (cap, census tract, etc.)


def _is_x(v) -> bool:
    """The AWL workbook marks set-aside elections with an 'X'."""
    if pd.isna(v):
        return False
    return str(v).strip().upper() == "X"


def load_applications(xlsx_path: Path) -> List[Application]:
    """Parse the TDHCA Award/Waiting List workbook into Application records."""
    df = pd.read_excel(xlsx_path, sheet_name="Submissions", header=10)

    # The workbook interleaves real apps with section headers like
    # "At-Risk Set-Aside" and "Region 1/Rural" in column A. Real app
    # numbers are 5-digit strings (e.g., "25038").
    df["app_str"] = df["Application Number"].astype(str)
    df = df[df["app_str"].str.match(r"^\d{5}$", na=False)].reset_index(drop=True)

    apps: List[Application] = []
    for _, row in df.iterrows():
        # Tie-breaker columns have weird whitespace in the header
        tb_usda_col = next((c for c in df.columns if "USDA" in c and "Tie" in c), None)
        tb_amen_col = next((c for c in df.columns if "Amenities" in c and "Tie" in c), None)
        target_col  = next((c for c in df.columns if "Target Population" in c), None)

        rec = "" if pd.isna(row["Recommendation"]) else str(row["Recommendation"]).strip()
        contact = "" if pd.isna(row.get("Primary Contact")) else (
            re.sub(r"\s+", " ", str(row["Primary Contact"]).strip())
        )
        ct = "" if pd.isna(row.get("Census Tract(s)")) else str(row["Census Tract(s)"]).strip()

        apps.append(Application(
            app_id            = row["app_str"],
            name              = str(row["Development Name"]),
            city              = str(row["City"]),
            region            = int(row["Region"]),
            urban_rural       = str(row["Urban/Rural"]).strip(),
            at_risk           = _is_x(row["At-Risk"]),
            usda              = _is_x(row["USDA"]),
            nonprofit         = _is_x(row["Nonprofit"]),
            construction_type = str(row["Construction Type"]).strip(),
            total_units       = int(row["Total Units"]) if pd.notna(row["Total Units"]) else 0,
            target_population = str(row[target_col]).strip() if target_col else "",
            htc_request       = float(row["HTC Request"]) if pd.notna(row["HTC Request"]) else 0.0,
            self_score        = float(row["Self Score Total"]) if pd.notna(row["Self Score Total"]) else 0.0,
            total_score       = float(row["Total Score"]) if pd.notna(row["Total Score"]) else 0.0,
            tb_usda           = float(row[tb_usda_col]) if tb_usda_col and pd.notna(row[tb_usda_col]) else 0.0,
            tb_amenities      = float(row[tb_amen_col]) if tb_amen_col and pd.notna(row[tb_amen_col]) else 0.0,
            actual_recommendation = rec,
            primary_contact   = contact,
            census_tract      = ct,
        ))
    return apps


# ---------------------------------------------------------------------------
# RANKING + TIE-BREAKER (§11.7)
# ---------------------------------------------------------------------------
# §11.7 tie-breaker order (after Total Score):
#   (1) USDA tie-breaker — relevant in the USDA Set-Aside step
#   (2) Amenities tie-breaker total
#
# We sort highest-first on score, then on tie-breakers. We use a stable
# tertiary sort on app_id so results are deterministic.

def _sort_key(app: Application, prefer_usda_tb: bool = False) -> tuple:
    primary_tb = -app.tb_usda if prefer_usda_tb else 0.0
    return (
        -app.total_score,         # higher score first
        primary_tb,               # USDA TB (higher first) when relevant
        -app.tb_amenities,        # amenities TB (higher first)
        app.app_id,               # stable
    )


def rank(apps: List[Application], prefer_usda_tb: bool = False) -> List[Application]:
    return sorted(apps, key=lambda a: _sort_key(a, prefer_usda_tb))


# ---------------------------------------------------------------------------
# §11.6 ALLOCATION ALGORITHM (Steps 1–6)
# ---------------------------------------------------------------------------

# Per-applicant cap (§11.4(a)): no Applicant/Developer/Affiliate may receive
# Housing Tax Credits in an aggregate amount greater than $6 million in a
# single Application Round. v1.5 implementation: track cumulative credits
# already awarded to each unique Primary Contact and skip the next app
# from that contact if it would push them over the cap.
#
# This is a SIMPLIFICATION: the QAP defines "Applicant/Developer/Affiliate"
# in terms of common Control, which can span Primary Contacts. v1.5 uses
# Primary Contact as a proxy because that is the field available in the
# AWL workbook. A full implementation would require entity resolution
# across Applicant Name, Developer Name, and Affiliate disclosures.

PER_APPLICANT_CAP = 6_000_000.00


@dataclass
class AllocationState:
    """Mutable state carried through the 6-step allocation."""
    awarded: List[Application] = field(default_factory=list)
    subregion_remaining: Dict[Tuple[int, str], float] = field(default_factory=dict)
    at_risk_remaining: float = AT_RISK_POOL
    usda_remaining:    float = USDA_POOL
    contact_awarded:   Dict[str, float] = field(default_factory=dict)
    awarded_tracts:    Dict[Tuple[str, int, str], str] = field(default_factory=dict)
    # Toggles for ablation: turn rules on/off to measure their contribution
    enforce_applicant_cap: bool = True
    enforce_tract_dedup:   bool = True

    def __post_init__(self):
        if not self.subregion_remaining:
            self.subregion_remaining = dict(SUBREGION_CEILINGS)

    def applicant_cap_blocks(self, app: Application) -> bool:
        """True if awarding this app would push its Primary Contact over $6M."""
        if not self.enforce_applicant_cap or not app.primary_contact:
            return False
        already = self.contact_awarded.get(app.primary_contact, 0.0)
        return (already + app.htc_request) > PER_APPLICANT_CAP + 1.0  # tolerance

    def tract_blocks(self, app: Application) -> bool:
        """§11.3(g) — in urban subregions, only one award per census tract.
        Does not apply in USDA or At-Risk Set-Asides per the QAP."""
        if not self.enforce_tract_dedup:
            return False
        if app.urban_rural != "Urban" or not app.census_tract:
            return False
        # USDA and At-Risk SAs are exempt; we check during subregion selection
        key = (app.census_tract, app.region, app.urban_rural)
        return key in self.awarded_tracts

    def award(self, app: Application, via: str, charge_subregion: bool = True) -> None:
        app.awarded = True
        app.awarded_via = via
        app.excluded_by = ""
        self.awarded.append(app)
        if charge_subregion:
            key = (app.region, app.urban_rural)
            self.subregion_remaining[key] = self.subregion_remaining.get(key, 0.0) - app.htc_request
        if app.primary_contact:
            self.contact_awarded[app.primary_contact] = self.contact_awarded.get(app.primary_contact, 0.0) + app.htc_request
        if app.urban_rural == "Urban" and app.census_tract:
            self.awarded_tracts[(app.census_tract, app.region, app.urban_rural)] = app.app_id


def _try_award(
    app: Application,
    state: AllocationState,
    via: str,
    charge_subregion: bool,
    enforce_tract: bool = True,
) -> bool:
    """Common award gate: check eligibility filters first."""
    if app.htc_request <= 0:
        return False
    if state.applicant_cap_blocks(app):
        app.excluded_by = "applicant_cap"
        return False
    if enforce_tract and state.tract_blocks(app):
        app.excluded_by = "census_tract"
        return False
    state.award(app, via, charge_subregion=charge_subregion)
    return True


def step1_usda_setaside(apps: List[Application], state: AllocationState) -> None:
    """§11.6(b)(3)(A) — USDA Set-Aside (statewide), pool ≈ $4.58M.

    Highest-scoring USDA-elected applications until the USDA pool is met.
    USDA awards consume from the At-Risk pool too (USDA is carved from At-Risk).
    Census tract dedup is exempt per §11.3(g).
    """
    candidates = [a for a in apps if a.usda and not a.awarded]
    for app in rank(candidates, prefer_usda_tb=True):
        if state.usda_remaining <= 0:
            break
        if _try_award(app, state, "USDA SA", charge_subregion=False, enforce_tract=False):
            state.usda_remaining  -= app.htc_request
            state.at_risk_remaining -= app.htc_request


def step2_atrisk_setaside(apps: List[Application], state: AllocationState) -> None:
    """§11.6(b)(3)(B) — At-Risk Set-Aside (statewide), pool ≈ $13.73M.

    Highest-scoring At-Risk-elected apps until pool is met. If pool not
    filled, USDA-flagged-but-At-Risk-eligible apps spill in.
    Census tract dedup is exempt per §11.3(g).
    """
    candidates = [a for a in apps if a.at_risk and not a.awarded]
    for app in rank(candidates):
        if state.at_risk_remaining <= 0:
            break
        if _try_award(app, state, "AtRisk SA", charge_subregion=False, enforce_tract=False):
            state.at_risk_remaining -= app.htc_request

    if state.at_risk_remaining > 0:
        usda_spillover = [a for a in apps if a.usda and not a.awarded]
        for app in rank(usda_spillover):
            if state.at_risk_remaining <= 0:
                break
            if _try_award(app, state, "USDA→AtRisk", charge_subregion=False, enforce_tract=False):
                state.at_risk_remaining -= app.htc_request


def step3_initial_subregion_selection(apps: List[Application], state: AllocationState) -> None:
    """§11.6(b)(3)(C) — Initial Selection in Each Subregion.

    Pick highest-scoring non-set-aside apps within each of the 26 subregions
    until the subregion pool is exhausted. Census tract dedup applies in
    urban subregions (§11.3(g)). $6M applicant cap applies universally.
    """
    by_subregion: Dict[Tuple[int, str], List[Application]] = {}
    for app in apps:
        if app.awarded or app.at_risk or app.usda:
            continue
        by_subregion.setdefault((app.region, app.urban_rural), []).append(app)

    for sub, candidates in by_subregion.items():
        for app in rank(candidates):
            if state.subregion_remaining.get(sub, 0.0) <= 0:
                break
            _try_award(app, state, "Subregion", charge_subregion=True, enforce_tract=True)


def step4_rural_collapse(apps: List[Application], state: AllocationState) -> None:
    """§11.6(b)(3)(D) — Rural Regional Collapse.

    Unspent rural subregion credits are pooled. Award statewide rural apps
    not yet awarded, by score. Census tract dedup does not strictly apply
    in rural subregions (§11.3(g) is urban-specific).
    """
    rural_pool = sum(
        max(0.0, remaining)
        for (region, ur), remaining in state.subregion_remaining.items()
        if ur == "Rural"
    )
    if rural_pool <= 0:
        return

    candidates = [a for a in apps if (not a.awarded) and (a.urban_rural == "Rural")
                  and (not a.at_risk) and (not a.usda)]
    for app in rank(candidates):
        if rural_pool <= 0:
            break
        if _try_award(app, state, "Rural Collapse", charge_subregion=False, enforce_tract=False):
            rural_pool -= app.htc_request


def step5_state_collapse(apps: List[Application], state: AllocationState) -> None:
    """§11.6(b)(3)(E) — Statewide Collapse.

    All remaining unspent credits are pooled. Award next-highest-scoring
    apps statewide until exhausted.
    """
    pool = sum(max(0.0, r) for r in state.subregion_remaining.values())
    pool += max(0.0, state.at_risk_remaining)

    if pool <= 0:
        return

    candidates = [a for a in apps if not a.awarded and not a.at_risk and not a.usda]
    for app in rank(candidates):
        if pool <= 0:
            break
        if _try_award(app, state, "State Collapse", charge_subregion=False, enforce_tract=True):
            pool -= app.htc_request


def step6_nonprofit_contingent(apps: List[Application], state: AllocationState) -> None:
    """§11.6(b)(3)(F) — Contingent Qualified Nonprofit Set-Aside (10%).

    If after Steps 1-5 the 10% nonprofit minimum is unmet, swap in the
    next-highest-scoring nonprofit app(s) statewide. v1 implementation:
    add nonprofit apps without de-awarding existing winners (not strict
    swap behavior; flagged as a known simplification).
    """
    nonprofit_total = sum(a.htc_request for a in state.awarded if a.nonprofit)
    if nonprofit_total >= NONPROFIT_MIN:
        return

    deficit = NONPROFIT_MIN - nonprofit_total
    candidates = [a for a in apps if not a.awarded and a.nonprofit]
    for app in rank(candidates):
        if deficit <= 0:
            break
        if _try_award(app, state, "NP Contingent", charge_subregion=False, enforce_tract=True):
            deficit -= app.htc_request


def run_allocation(
    apps: List[Application],
    enforce_applicant_cap: bool = True,
    enforce_tract_dedup: bool = True,
) -> AllocationState:
    """Execute the full §11.6 allocation pipeline.

    Toggle args let the ablation harness disable individual rules to
    measure each rule's contribution to overall recall.
    """
    state = AllocationState(
        enforce_applicant_cap=enforce_applicant_cap,
        enforce_tract_dedup=enforce_tract_dedup,
    )
    step1_usda_setaside(apps, state)
    step2_atrisk_setaside(apps, state)
    step3_initial_subregion_selection(apps, state)
    step4_rural_collapse(apps, state)
    step5_state_collapse(apps, state)
    step6_nonprofit_contingent(apps, state)
    return state


# ---------------------------------------------------------------------------
# SYNTHETIC PROJECT INJECTION
# ---------------------------------------------------------------------------
# Per the prospectus: "A synthetic project generator will allow controlled
# creation of theoretical developments whose attributes can be systematically
# varied. These projects will be injected into historical applicant pools to
# estimate their likelihood of funding."
#
# A synthetic project is just an Application with app_id like "SYN-..." and
# actual_recommendation = "" (no ground truth). It runs through the full
# §11.6 pipeline and gets a predicted award/no-award.
#
# Use load_synthetic() to read a JSON spec, or build_synthetic() in code.

import json


def build_synthetic(
    name: str,
    region: int,
    urban_rural: str,
    total_score: float,
    htc_request: float,
    at_risk: bool = False,
    usda: bool = False,
    nonprofit: bool = False,
    construction_type: str = "New Construction",
    target_population: str = "General",
    total_units: int = 80,
    tb_amenities: float = 0.0,
    tb_usda: float = 0.0,
    syn_id: Optional[str] = None,
) -> Application:
    """Build a synthetic Application for injection.

    All keyword args mirror the Application fields the simulator actually
    consumes. Defaults are chosen to be median-ish for a 2025 TX 9% pool.
    """
    return Application(
        app_id            = syn_id or f"SYN-{name[:20].replace(' ','_')}",
        name              = name,
        city              = "(synthetic)",
        region            = region,
        urban_rural       = urban_rural,
        at_risk           = at_risk,
        usda              = usda,
        nonprofit         = nonprofit,
        construction_type = construction_type,
        total_units       = total_units,
        target_population = target_population,
        htc_request       = htc_request,
        self_score        = total_score,
        total_score       = total_score,
        tb_usda           = tb_usda,
        tb_amenities      = tb_amenities,
        actual_recommendation = "",   # no ground truth
    )


def load_synthetic(json_path: Path) -> List[Application]:
    """Load one or more synthetic projects from a JSON file.

    File can be a single object or a list of objects; each object is
    passed as kwargs to build_synthetic().
    """
    with open(json_path) as f:
        data = json.load(f)
    specs = data if isinstance(data, list) else [data]
    return [build_synthetic(**spec) for spec in specs]


def inject_and_run(
    real_apps: List[Application],
    synthetic_apps: List[Application],
) -> Tuple[AllocationState, List[Application]]:
    """Inject synthetic projects into the real pool and run §11.6.

    Returns (state, all_apps). Only synthetic projects with awarded=True
    in the returned all_apps are predicted to win an award.
    """
    pool = real_apps + synthetic_apps
    # Reset award state on the real pool in case the caller re-uses it
    for a in pool:
        a.awarded = False
        a.awarded_via = ""
        a.excluded_by = ""
    state = run_allocation(pool)
    return state, pool


# ---------------------------------------------------------------------------
# PER-RULE ABLATION
# ---------------------------------------------------------------------------
# Toggle each rule on/off and measure the contribution to overall recall.
# Useful for the methodology section: shows which institutional rules
# matter most for prediction quality, not just *that* the simulator works.

def ablation(workbook_path: Path) -> List[Dict[str, object]]:
    """Run the simulator under every combination of rule toggles and
    return a results table.
    """
    results = []
    for cap, tract in [(False, False), (True, False), (False, True), (True, True)]:
        apps = load_applications(workbook_path)
        run_allocation(apps, enforce_applicant_cap=cap, enforce_tract_dedup=tract)
        rep = validate(apps)
        results.append({
            "applicant_cap":  cap,
            "tract_dedup":    tract,
            "tp":             rep.true_positives,
            "fp":             rep.false_positives,
            "fn":             rep.false_negatives,
            "recall":         rep.award_recall,
            "precision":      rep.award_precision,
            "accuracy":       rep.match_rate,
        })
    return results


# ---------------------------------------------------------------------------
# TIE-BREAK SENSITIVITY ANALYSIS
# ---------------------------------------------------------------------------
# The §11.7 cascade (proximity to park, elementary school, sum of distances,
# linear distance to nearest LIHTC dev with same target pop) is not fully
# represented in public data — the AWL workbook only gives the summary
# "Amenities Tie-Breaker Total." When apps cluster at the same Total Score
# in the same subregion, the realized winner depends on per-foot proximity
# data we don't have.
#
# This Monte Carlo perturbs ties randomly to bound the recall/precision
# range achievable by ANY tie-break ordering on the data we have.

import random


def sensitivity_tiebreak(
    apps: List[Application],
    n_trials: int = 200,
    seed: int = 42,
) -> Dict[str, float]:
    """Bound the recall/precision range across all tie-break orderings
    consistent with just the public Total Score.

    The AWL workbook reports a summary "Amenities Tie-Breaker Total" but
    the QAP §11.7 cascade resolves ties using per-feature proximity data
    that is not in any public file (park, elementary school, sum-of-
    distances within 100 ft, linear distance to nearest LIHTC dev with
    same target population). To honestly bound model uncertainty, we
    randomize ordering among apps tied on Total Score within each
    (region, urban_rural) cell.

    Returns min / mean / max recall and precision across n_trials.
    """
    rng = random.Random(seed)
    recalls, precisions = [], []

    # Snapshot the original tie-break columns
    orig_amen = {a.app_id: a.tb_amenities for a in apps}
    orig_usda = {a.app_id: a.tb_usda      for a in apps}

    for _ in range(n_trials):
        for a in apps:
            a.awarded = False
            a.awarded_via = ""
            # Random jitter dominates the original TB columns,
            # so within a Total-Score tie the order is fully random.
            a.tb_amenities = rng.random()
            a.tb_usda      = rng.random()

        run_allocation(apps)
        rep = validate(apps)
        recalls.append(rep.award_recall)
        precisions.append(rep.award_precision)

    # Restore originals
    for a in apps:
        a.tb_amenities = orig_amen[a.app_id]
        a.tb_usda      = orig_usda[a.app_id]
        a.awarded = False
        a.awarded_via = ""

    return {
        "recall_min":     min(recalls),
        "recall_mean":    sum(recalls) / len(recalls),
        "recall_max":     max(recalls),
        "precision_min":  min(precisions),
        "precision_mean": sum(precisions) / len(precisions),
        "precision_max":  max(precisions),
        "n_trials":       n_trials,
    }


# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    n_apps: int
    n_actual_awards: int
    n_predicted_awards: int
    true_positives: int          # predicted Award AND actually Award
    false_positives: int         # predicted Award but not actually Award
    false_negatives: int         # actually Award but not predicted Award
    match_rate: float            # TP / N_apps  (overall classification accuracy)
    award_recall: float          # TP / N_actual_awards
    award_precision: float       # TP / N_predicted_awards
    misses: List[Application] = field(default_factory=list)
    false_predictions: List[Application] = field(default_factory=list)


def validate(apps: List[Application]) -> ValidationReport:
    actual = {a.app_id for a in apps if a.actual_recommendation == "Award"}
    pred   = {a.app_id for a in apps if a.awarded}

    tp = len(actual & pred)
    fp = len(pred - actual)
    fn = len(actual - pred)
    correct = tp + sum(1 for a in apps if (a.app_id not in actual) and (a.app_id not in pred))

    misses = [a for a in apps if a.app_id in (actual - pred)]
    false_preds = [a for a in apps if a.app_id in (pred - actual)]

    return ValidationReport(
        n_apps              = len(apps),
        n_actual_awards     = len(actual),
        n_predicted_awards  = len(pred),
        true_positives      = tp,
        false_positives     = fp,
        false_negatives     = fn,
        match_rate          = correct / len(apps) if apps else 0.0,
        award_recall        = tp / len(actual) if actual else 0.0,
        award_precision     = tp / len(pred)   if pred else 0.0,
        misses              = misses,
        false_predictions   = false_preds,
    )


def print_report(state: AllocationState, report: ValidationReport, apps: List[Application] = None) -> None:
    print("=" * 72)
    print("Texas 9% HTC Simulator — 2025 Cycle Validation")
    print("=" * 72)
    print(f"Applications in pool:        {report.n_apps}")
    print(f"Actual awards (TDHCA):       {report.n_actual_awards}")
    print(f"Predicted awards (sim):      {report.n_predicted_awards}")
    print()
    print(f"True positives:              {report.true_positives}")
    print(f"False positives:             {report.false_positives}")
    print(f"False negatives:             {report.false_negatives}")
    print()
    print(f"Overall classification acc:  {report.match_rate:.1%}")
    print(f"Award recall (TP/actual):    {report.award_recall:.1%}")
    print(f"Award precision (TP/pred):   {report.award_precision:.1%}")
    print()
    print("Awards by allocation step:")
    by_step: Dict[str, int] = {}
    for a in state.awarded:
        by_step[a.awarded_via] = by_step.get(a.awarded_via, 0) + 1
    for step, n in sorted(by_step.items()):
        print(f"  {step:18s}  {n}")

    # Show rule firings: how many apps were blocked by which eligibility rule
    if apps is not None:
        blocked = {"applicant_cap": 0, "census_tract": 0}
        for a in apps:
            if a.excluded_by in blocked:
                blocked[a.excluded_by] += 1
        if any(blocked.values()):
            print()
            print("Eligibility-rule firings (apps blocked):")
            for rule, n in blocked.items():
                if n:
                    print(f"  {rule:18s}  {n}")

    if report.misses:
        print()
        print(f"FALSE NEGATIVES (TDHCA awarded, sim did not) — {len(report.misses)}:")
        for a in sorted(report.misses, key=lambda x: -x.total_score):
            tags = []
            if a.at_risk:   tags.append("AtRisk")
            if a.usda:      tags.append("USDA")
            if a.nonprofit: tags.append("NP")
            tag_str = ",".join(tags) if tags else "general"
            why = f" [blocked: {a.excluded_by}]" if a.excluded_by else ""
            print(f"  {a.app_id}  {a.name[:40]:40s}  R{a.region}/{a.urban_rural[:1]}  "
                  f"score={a.total_score:5.1f}  req=${a.htc_request:>10,.0f}  [{tag_str}]{why}")

    if report.false_predictions:
        print()
        print(f"FALSE POSITIVES (sim awarded, TDHCA did not) — {len(report.false_predictions)}:")
        for a in sorted(report.false_predictions, key=lambda x: -x.total_score):
            tags = []
            if a.at_risk:   tags.append("AtRisk")
            if a.usda:      tags.append("USDA")
            if a.nonprofit: tags.append("NP")
            tag_str = ",".join(tags) if tags else "general"
            print(f"  {a.app_id}  {a.name[:40]:40s}  R{a.region}/{a.urban_rural[:1]}  "
                  f"score={a.total_score:5.1f}  req=${a.htc_request:>10,.0f}  "
                  f"via={a.awarded_via}  [{tag_str}]")


# ---------------------------------------------------------------------------
# STANDARDIZED CROSS-MECHANISM PREDICTION SCHEMA
# ---------------------------------------------------------------------------
# All three simulators (CA 9%/bond, TX 9%, TX 4%) write predictions to a
# common CSV schema so the cross-mechanism comparison harness in chat 03
# can read them without knowing each simulator's internals.

CROSS_MECHANISM_COLUMNS = [
    "mechanism",          # "TX_9pct" / "CA_9pct" / "TX_4pct"
    "cycle_year",         # int
    "app_id",             # str (state-local app number)
    "name",               # development name
    "regional_pool",      # subregion / city pool / lottery tier
    "set_aside_flags",    # comma-separated: "AtRisk,USDA,Nonprofit" etc.
    "score_or_priority",  # numeric score (TX/CA 9%) or priority tier (TX 4%)
    "request_amount",     # dollars requested
    "predicted_award",    # bool
    "predicted_via",      # which step/rule placed it
    "predicted_blocked_by", # eligibility rule that blocked it (if any)
    "actual_award",       # bool (ground truth where available)
]


def to_cross_mechanism_rows(apps: List[Application], cycle_year: int = 2025) -> List[Dict[str, object]]:
    """Convert TX9 Application list → standardized rows for cross-mech CSV."""
    rows = []
    for a in apps:
        flags = []
        if a.at_risk:   flags.append("AtRisk")
        if a.usda:      flags.append("USDA")
        if a.nonprofit: flags.append("Nonprofit")
        rows.append({
            "mechanism":            "TX_9pct",
            "cycle_year":           cycle_year,
            "app_id":               a.app_id,
            "name":                 a.name,
            "regional_pool":        f"R{a.region}/{a.urban_rural[:1]}",
            "set_aside_flags":      ",".join(flags),
            "score_or_priority":    a.total_score,
            "request_amount":       a.htc_request,
            "predicted_award":      a.awarded,
            "predicted_via":        a.awarded_via,
            "predicted_blocked_by": a.excluded_by,
            "actual_award":         a.actual_recommendation == "Award",
        })
    return rows


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workbook",
        type=Path,
        help="Path to 25261014HTC9pctAwardWaitingList.xlsx (TDHCA AWL workbook)",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Optional path to write per-application predictions as CSV.",
    )
    parser.add_argument(
        "--synthetic",
        type=Path,
        default=None,
        help="Optional JSON file with synthetic project(s) to inject into the pool.",
    )
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="Run tie-break Monte Carlo sensitivity analysis (200 trials).",
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="Run per-rule ablation table (4 toggle combinations).",
    )
    args = parser.parse_args()

    apps = load_applications(args.workbook)

    if args.synthetic:
        synth = load_synthetic(args.synthetic)
        state, all_apps = inject_and_run(apps, synth)
        report = validate([a for a in all_apps if a.actual_recommendation != ""])
        print_report(state, report, all_apps)
        print()
        print("=" * 72)
        print("Synthetic project results:")
        print("=" * 72)
        for a in synth:
            verdict = "AWARDED" if a.awarded else "NOT awarded"
            via = f" via {a.awarded_via}" if a.awarded else ""
            print(f"  {a.app_id:<30s} {verdict}{via}")
            print(f"     R{a.region}/{a.urban_rural[:1]}  score={a.total_score}  "
                  f"req=${a.htc_request:,.0f}")
    else:
        state = run_allocation(apps)
        report = validate(apps)
        print_report(state, report, apps)

    if args.ablation:
        print()
        print("=" * 72)
        print("Per-rule ablation (toggling §11.4(a) cap and §11.3(g) tract dedup)")
        print("=" * 72)
        print(f"{'cap':>5} {'tract':>6} {'TP':>4} {'FP':>4} {'FN':>4}  "
              f"{'recall':>8} {'precision':>10} {'accuracy':>10}")
        for r in ablation(args.workbook):
            print(f"{str(r['applicant_cap']):>5} {str(r['tract_dedup']):>6} "
                  f"{r['tp']:>4} {r['fp']:>4} {r['fn']:>4}  "
                  f"{r['recall']:>7.1%} {r['precision']:>9.1%} {r['accuracy']:>9.1%}")

    if args.sensitivity:
        print()
        print("=" * 72)
        print("Tie-break sensitivity analysis (200 random trials)")
        print("=" * 72)
        # Re-load apps to get clean state
        apps_fresh = load_applications(args.workbook)
        sens = sensitivity_tiebreak(apps_fresh, n_trials=200)
        print(f"Recall:    min {sens['recall_min']:.1%}  "
              f"mean {sens['recall_mean']:.1%}  max {sens['recall_max']:.1%}")
        print(f"Precision: min {sens['precision_min']:.1%}  "
              f"mean {sens['precision_mean']:.1%}  max {sens['precision_max']:.1%}")
        print(f"Trials: {sens['n_trials']}")

    if args.csv_out:
        rows = to_cross_mechanism_rows(apps, cycle_year=2025)
        pd.DataFrame(rows).to_csv(args.csv_out, index=False)
        print(f"\nWrote {len(rows)} rows (standardized schema) to {args.csv_out}")


if __name__ == "__main__":
    main()
