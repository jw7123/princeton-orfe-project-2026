import subprocess
import sys

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import pandas
except ImportError:
    install("pandas")

try:
    import xlwings
except ImportError:
    install("xlwings")

try:
    import openpyxl
except ImportError:
    install("openpyxl")

import pandas as pd
import xlwings as xw

# --- Load workbook and sheets ---
import os

# Automatically determine the folder the Excel macro is in
base_dir = os.path.dirname(os.path.abspath(__file__))

# Build paths relative to that folder
macro_workbook_path = os.path.join(base_dir, 'CA Bond Scoring Simulator.xlsm')
wb = xw.Book(macro_workbook_path)
ws = wb.sheets["Simulator"]
lac_ws = wb.sheets["LAC Deal Line"]

# --- Extract pool and category values from Simulator sheet ---
def get_cell_value_by_label(sheet, label):
    for row in range(7, 27):
        cell_label = sheet.range(row, 6).value
        if cell_label == label:
            value = sheet.range(row, 8).value
            if isinstance(value, str):
                value = float(value.replace("$", "").replace(",", ""))
            return value
    return None

# --- Read values from the Excel ---
BIPOC = float(get_cell_value_by_label(ws, 'BIPOC') or 0)
Preservation = float(get_cell_value_by_label(ws, 'Preservation') or 0)
Other_Rehabilitation = float(get_cell_value_by_label(ws, 'Other Rehabilitation') or 0)
Rural = float(get_cell_value_by_label(ws, 'Rural') or 0)
Homeless = float(get_cell_value_by_label(ws, 'Homeless') or 0)
ELI_VLI = float(get_cell_value_by_label(ws, 'ELI/VLI') or 0)
MIP_bonds = float(get_cell_value_by_label(ws, 'MIP (bonds)') or 0)
MIP_tax_credits = float(get_cell_value_by_label(ws, 'MIP (tax credits)') or 0)
New_Construction = float(get_cell_value_by_label(ws, 'New Construction') or 0)
Non_New_Construction = float(get_cell_value_by_label(ws, 'Non New Construction') or 0)
Farmworker_Housing = float(get_cell_value_by_label(ws, 'Farmworker Housing') or 0)

REGIONAL_FUNDS = {
    "Coastal": float(get_cell_value_by_label(ws, 'Coastal') or 0),
    "City of Los Angeles": float(get_cell_value_by_label(ws, 'City of Los Angeles') or 0),
    "Balance of Los Angeles County": float(get_cell_value_by_label(ws, 'Balance of Los Angeles County') or 0),
    "Bay Area": float(get_cell_value_by_label(ws, 'Bay Area') or 0),
    "Inland": float(get_cell_value_by_label(ws, 'Inland') or 0),
    "Northern": float(get_cell_value_by_label(ws, 'Northern') or 0)
}

REGION_NAME_MAPPING = {
    "Coastal (Monterey, Napa, Orange, San Benito, San Diego, San Luis Obispo, Santa Barbara, Sonoma, and Ventura Counties) ": "Coastal",
    "Bay Area (Alameda, Contra Costa, Marin, San Francisco, San Mateo, Santa Clara, and Santa Cruz Counties)": "Bay Area",
    "Inland (Fresno, Imperial, Kern, Kings, Madera, Merced, Riverside, San Bernardino, Stanislaus, and Tulare Counties)": "Inland",
    "Northern (Butte, El Dorado, Placer, Sacramento, San Joaquin, Shasta, Solano, Sutter, Yuba, and Yolo Counties)": "Northern",
    "Balance of Los Angeles County": "Balance of Los Angeles County",
    "City of Los Angeles": "City of Los Angeles"
}

MIN_SCORE = 89

# --- Load applicant data and test project ---
applicant_base_name = ws.range("D29").value
sheet_name = ws.range("D30").value
input_file = os.path.join(base_dir, f"{applicant_base_name}.xlsx")
output_file = os.path.join(base_dir, 'Awarded Projects.xlsx')

applicant_df = pd.read_excel(input_file, sheet_name=sheet_name, engine='openpyxl', header=1)

def get_test_project_from_inputs(lac_ws, expected_columns):
    headers = [cell.value for cell in lac_ws.range("A1").expand("right")]
    values = [cell.value for cell in lac_ws.range("A2").expand("right")]
    test_df = pd.DataFrame([values], columns=headers)
    for col in expected_columns:
        if col not in test_df.columns:
            test_df[col] = None
    test_df = test_df[expected_columns]
    return test_df

include_test_project = str(ws.range("D7").value).strip().lower() == 'yes'
if include_test_project:
    test_project_df = get_test_project_from_inputs(lac_ws, expected_columns=applicant_df.columns.tolist())
    if test_project_df is not None:
        applicant_df = pd.concat([applicant_df, test_project_df], ignore_index=True)

# --- Apply region mapping ---
applicant_df['POOL REGION'] = applicant_df['CDLAC REGION'].map(REGION_NAME_MAPPING)

# --- Setup funding pool variables ---
awarded_projects_df = pd.DataFrame(columns=applicant_df.columns).astype(applicant_df.dtypes.to_dict())

available_bipoc_funds = BIPOC
available_preservation_funds = Preservation
available_other_rehabilitation_funds = Other_Rehabilitation
available_rural_funds = Rural
available_homeless_funds = Homeless
available_eli_vli_funds = ELI_VLI
available_mip_bond_funds = MIP_bonds
available_mip_tax_credit_funds = MIP_tax_credits
available_new_construction_funds = New_Construction
available_non_new_construction_funds = Non_New_Construction
available_farmworker_funds = Farmworker_Housing
available_regional_funds = REGIONAL_FUNDS.copy()

def fund_projects(projects_df, available_funds, awarded_projects_df,
                  special_rule=False, mip_state_funds=False, region_name=None):
    global available_new_construction_funds, available_non_new_construction_funds
    global available_mip_tax_credit_funds, available_farmworker_funds

    funded_projects = []
    initial_funds = available_funds

    if special_rule:
        affh_10 = projects_df[projects_df["POINTS: AFFH"] == 10]
        used_funds = 0

        for _, project in affh_10.iterrows():
            app_number = project['APPLICATION NUMBER']
            if app_number in awarded_projects_df['APPLICATION NUMBER'].values:
                continue

            bond_request = project['BOND REQUEST']
            state_request = project['STATE CREDIT REQUEST']
            points = project['CDLAC TOTAL POINTS']

            if project.get("FARMWORKER") == "Yes":
                state_funds_available = available_farmworker_funds
            elif mip_state_funds:
                state_funds_available = available_mip_tax_credit_funds
            elif points > 110:
                state_funds_available = available_non_new_construction_funds
            else:
                state_funds_available = available_new_construction_funds

            if available_funds < 0.8 * bond_request or state_funds_available < 0.8 * state_request:
                continue

            actual_bond = min(bond_request, available_funds)
            actual_state = min(state_request, state_funds_available)
            available_funds -= actual_bond
            used_funds += actual_bond

            if project.get("FARMWORKER") == "Yes":
                available_farmworker_funds -= actual_state
            elif mip_state_funds:
                available_mip_tax_credit_funds -= actual_state
            elif points > 110:
                available_non_new_construction_funds -= actual_state
            else:
                available_new_construction_funds -= actual_state

            project_copy = project.copy()
            project_copy["FUNDED FROM"] = region_name or "Special Set-Aside"
            funded_projects.append(project_copy)

            if used_funds >= 0.5 * initial_funds:
                break

        remaining_projects = projects_df.loc[~projects_df['APPLICATION NUMBER'].isin(
            [p['APPLICATION NUMBER'] for p in funded_projects]
        )].copy()

        remaining_projects["ADJUSTED_SCORE"] = remaining_projects["CDLAC TOTAL POINTS"] - remaining_projects["POINTS: AFFH"]

        adjusted_sorted = remaining_projects.sort_values(
            by=["ADJUSTED_SCORE", "TIEBREAKER SELF SCORE"],
            ascending=[False, False]
        )

        for _, project in adjusted_sorted.iterrows():
            app_number = project['APPLICATION NUMBER']
            bond_request = project['BOND REQUEST']
            state_request = project['STATE CREDIT REQUEST']
            points = project['CDLAC TOTAL POINTS']
            if points < MIN_SCORE:
                continue

            if app_number in awarded_projects_df['APPLICATION NUMBER'].values:
                continue

            if project.get("FARMWORKER") == "Yes":
                state_funds_available = available_farmworker_funds
            elif mip_state_funds:
                state_funds_available = available_mip_tax_credit_funds
            elif points > 110:
                state_funds_available = available_non_new_construction_funds
            else:
                state_funds_available = available_new_construction_funds

            if available_funds < 0.8 * bond_request or state_funds_available < 0.8 * state_request:
                continue

            actual_bond = min(bond_request, available_funds)
            actual_state = min(state_request, state_funds_available)
            available_funds -= actual_bond

            if project.get("FARMWORKER") == "Yes":
                available_farmworker_funds -= actual_state
            elif mip_state_funds:
                available_mip_tax_credit_funds -= actual_state
            elif points > 110:
                available_non_new_construction_funds -= actual_state
            else:
                available_new_construction_funds -= actual_state

            project_copy = project.copy()
            project_copy["FUNDED FROM"] = region_name or "Special Set-Aside"
            funded_projects.append(project_copy)

        return funded_projects, available_funds

    for _, project in projects_df.iterrows():
        app_number = project['APPLICATION NUMBER']
        if app_number in awarded_projects_df['APPLICATION NUMBER'].values:
            continue

        bond_request = project['BOND REQUEST']
        state_request = project['STATE CREDIT REQUEST']
        points = project['CDLAC TOTAL POINTS']
        if points < MIN_SCORE:
            continue

        if project.get("FARMWORKER") == "Yes":
            state_funds_available = available_farmworker_funds
        elif mip_state_funds:
            state_funds_available = available_mip_tax_credit_funds
        elif points > 110:
            state_funds_available = available_non_new_construction_funds
        else:
            state_funds_available = available_new_construction_funds

        if available_funds < 0.8 * bond_request or state_funds_available < 0.8 * state_request:
            continue

        actual_bond = min(bond_request, available_funds)
        actual_state = min(state_request, state_funds_available)
        available_funds -= actual_bond

        if project.get("FARMWORKER") == "Yes":
            available_farmworker_funds -= actual_state
        elif mip_state_funds:
            available_mip_tax_credit_funds -= actual_state
        elif points > 110:
            available_non_new_construction_funds -= actual_state
        else:
            available_new_construction_funds -= actual_state

        project_copy = project.copy()
        project_copy["FUNDED FROM"] = region_name or "Category Match"
        funded_projects.append(project_copy)

    return funded_projects, available_funds

# --- Category-based allocations ---
categories = [
    ('BIPOC PREQUALIFIED', 'Yes', available_bipoc_funds, False, False),
    ('CDLAC POOL', 'Preservation', available_preservation_funds, False, False),
    ('CDLAC POOL', 'Other Rehabilitation', available_other_rehabilitation_funds, False, False),
    ('RURAL', 'Yes', available_rural_funds, False, False),
    ('HOMELESS', 'Yes', available_homeless_funds, True, False),
    ('ELI/VLI', 'Yes', available_eli_vli_funds, True, False),
    ('MIP', 'Yes', available_mip_bond_funds, True, True)
]

for column, value, funds_total, special_rule, mip_state in categories:
    filtered = applicant_df[applicant_df[column] == value].copy()
    sorted_projects = filtered.sort_values(by=['CDLAC TOTAL POINTS', 'TIEBREAKER SELF SCORE'], ascending=[False, False])
    funded, _ = fund_projects(sorted_projects, funds_total, awarded_projects_df, special_rule, mip_state, column)
    new_df = pd.DataFrame(funded)
    if not awarded_projects_df.dropna(how='all').empty and not new_df.dropna(how='all').empty:
        awarded_projects_df = pd.concat([awarded_projects_df, new_df], ignore_index=True)
    elif not new_df.dropna(how='all').empty:
        awarded_projects_df = new_df.copy()




# --- Regional allocation with fallback logic ---
for region, funds_total in REGIONAL_FUNDS.items():
    region_projects = applicant_df[
        (applicant_df['POOL REGION'] == region) &
        (applicant_df['RURAL'] != 'Yes') &
        (applicant_df['CONSTRUCTION TYPE'].str.strip().str.lower() == 'new construction')
    ].copy()

    sorted_projects = region_projects.sort_values(by=['CDLAC TOTAL POINTS', 'TIEBREAKER SELF SCORE'], ascending=[False, False])
    funded, remaining = fund_projects(sorted_projects, funds_total, awarded_projects_df, special_rule=True, mip_state_funds=False, region_name=region)
    new_df = pd.DataFrame(funded)
    if not awarded_projects_df.dropna(how='all').empty and not new_df.dropna(how='all').empty:
        awarded_projects_df = pd.concat([awarded_projects_df, new_df], ignore_index=True)
    elif not new_df.dropna(how='all').empty:
        awarded_projects_df = new_df.copy()


    available_regional_funds[region] = remaining

# --- Output results ---
awarded_projects_df.to_excel(output_file, sheet_name='Award_List', index=False)

# --- Feedback for test project ---
test_project_name = ws.range("D13").value
included_flag = str(ws.range("D7").value).strip().lower() == 'yes'

if not included_flag:
    ws.range("D8").value = "N/A"
elif test_project_name in awarded_projects_df['PROJECT NAME'].values:
    ws.range("D8").value = "Yes"
else:
    ws.range("D8").value = "No"

row = awarded_projects_df[awarded_projects_df['PROJECT NAME'] == test_project_name]
if not row.empty:
    ws.range("D9").value = row['FUNDED FROM'].iloc[0]
else:
    ws.range("D9").value = ""

if test_project_name in awarded_projects_df['PROJECT NAME'].values:
    rank = (
        awarded_projects_df.reset_index()
        .query("`PROJECT NAME` == @test_project_name")
        .index[0] + 1
    )
    ws.range("D10").value = rank
else:
    ws.range("D10").value = ""

