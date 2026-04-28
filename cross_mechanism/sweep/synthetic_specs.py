"""
sweep/synthetic_specs.py
========================

The six archetypal project specifications used in the synthetic-project sweep
in chapter 5. Each spec is defined once and translated per-mechanism by the
adapter functions in `sweep_runner.py`.

The specs are designed to span the dimensions the three mechanisms reward
differently:

- HIGH_SCORE_URBAN_NC : top-quartile urban new construction with a strong
                        scoring profile in any competitive scoring mechanism
- LOW_SCORE_URBAN_NC  : urban new construction with a deliberately weak
                        scoring profile (below the CA 89-point minimum and
                        in the bottom quartile of the TX 9% distribution)
- RURAL_PRESERVATION  : rural rehab/preservation; benefits from
                        rural/USDA set-asides and at-risk priority
- HOMELESS_PSH        : permanent supportive housing; should benefit from
                        targeted-population scoring boosts
- FARMWORKER          : a project tagged for the farmworker special-needs
                        population; relevant to CA's state-credit farmworker
                        carve-out and to USDA-coded rural pools in TX
- MID_QUEUE_TX4       : a TX 4% archetype --- median-priority-date general
                        urban new construction; useful as a baseline against
                        which to measure how much TX 4% outcome depends on
                        priority date alone

For TX 9% the spec → Application mapping uses:
- Region 3 (Dallas/Plano metroplex) for the urban-NC specs because it has
  the largest 2025 subregion ceiling and the largest applicant pool in our
  data, so injection effects are most visible there.
- Region 4 Rural for RURAL_PRESERVATION (East Texas; significant rural
  applicant pool in 2025).
- Region 6 Urban for HOMELESS_PSH (Houston; large supportive-housing
  pipeline historically).
- Region 11 Rural for FARMWORKER, with USDA flag set (Rio Grande Valley;
  the natural Texas region for a farmworker spec).
- Region 7 Urban for MID_QUEUE_TX4 (Austin; mid-size urban subregion).
"""

# Each spec is a dict the mechanism adapters consume. Fields not used by a
# given mechanism are silently ignored.

SYNTHETIC_SPECS = [
    {
        "spec_id": "HIGH_SCORE_URBAN_NC",
        "description": "Top-quartile urban new construction",
        # TX 9% mapping
        "tx9": {
            "name": "Synthetic: High-Score Urban NC (R3)",
            "region": 3,
            "urban_rural": "Urban",
            "total_score": 170.0,
            "htc_request": 1_750_000.0,
            "construction_type": "New Construction",
            "target_population": "General",
            "total_units": 100,
            "tb_amenities": 6_000.0,
        },
    },
    {
        "spec_id": "LOW_SCORE_URBAN_NC",
        "description": "Urban new construction with weak scoring profile",
        "tx9": {
            "name": "Synthetic: Low-Score Urban NC (R3)",
            "region": 3,
            "urban_rural": "Urban",
            "total_score": 130.0,
            "htc_request": 1_750_000.0,
            "construction_type": "New Construction",
            "target_population": "General",
            "total_units": 80,
            "tb_amenities": 1_500.0,
        },
    },
    {
        "spec_id": "RURAL_PRESERVATION",
        "description": "Rural at-risk preservation rehab",
        "tx9": {
            "name": "Synthetic: Rural Preservation (R4)",
            "region": 4,
            "urban_rural": "Rural",
            "total_score": 168.0,
            "htc_request": 800_000.0,
            "at_risk": True,
            "construction_type": "Acquisition/Rehab",
            "target_population": "General",
            "total_units": 60,
            "tb_amenities": 2_500.0,
        },
    },
    {
        "spec_id": "HOMELESS_PSH",
        "description": "Permanent supportive housing for chronically homeless",
        "tx9": {
            "name": "Synthetic: Supportive Housing (R6)",
            "region": 6,
            "urban_rural": "Urban",
            "total_score": 173.0,
            "htc_request": 1_500_000.0,
            "construction_type": "New Construction",
            "target_population": "Supportive Housing",
            "total_units": 80,
            "tb_amenities": 5_000.0,
        },
    },
    {
        "spec_id": "FARMWORKER",
        "description": "Farmworker special-needs project",
        "tx9": {
            "name": "Synthetic: Farmworker USDA Rural (R11)",
            "region": 11,
            "urban_rural": "Rural",
            "total_score": 165.0,
            "htc_request": 700_000.0,
            "usda": True,
            "construction_type": "New Construction",
            "target_population": "General",
            "total_units": 50,
            "tb_amenities": 1_500.0,
        },
    },
    {
        "spec_id": "MID_QUEUE_TX4",
        "description": "TX 4% archetype: median-priority general urban NC",
        "tx9": {
            "name": "Synthetic: Mid-Tier Urban NC (R7)",
            "region": 7,
            "urban_rural": "Urban",
            "total_score": 168.0,
            "htc_request": 1_500_000.0,
            "construction_type": "New Construction",
            "target_population": "General",
            "total_units": 90,
            "tb_amenities": 4_000.0,
        },
    },
]
