"""
softmax_simulator.py
Simulates SoftMax Pro plate reader for a TNF-alpha ELISA (HSTA00E).
Generates biology-driven OD values per well using kit typical data.
Reads hamilton_complete.flag and plate_state.csv.
Outputs raw_od_data.csv and softmax_complete.flag.
Run after hamilton_simulator.py.
"""

import pandas as pd
import numpy as np
import os
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS       = config["paths"]
ASSAY       = config["assay"]
INSTRUMENTS = config["instruments"]

np.random.seed(42)  # reproducible simulation

# --- Check dependencies ---
hamilton_flag_path = os.path.join(PATHS["flags"], "hamilton_complete.flag")
plate_state_path   = os.path.join(PATHS["data_output"], "plate_state.csv")

if not os.path.exists(hamilton_flag_path):
    raise FileNotFoundError("hamilton_complete.flag not found. Run hamilton_simulator.py first.")

if not os.path.exists(plate_state_path):
    raise FileNotFoundError("plate_state.csv not found. Run plate_state.py first.")

with open(hamilton_flag_path) as f:
    flag = json.load(f)

if flag["status"] != "complete":
    raise RuntimeError(
        f"Hamilton run did not complete successfully.\n"
        f"  Failed steps: {flag['failed_steps']}\n"
        f"  -> Investigate before proceeding."
    )

plate_state_df = pd.read_csv(plate_state_path)

print(f"Plate state loaded : {len(plate_state_df)} wells")
print(f"Plate ID           : {flag['plate_id']}")
print(f"Instrument         : {INSTRUMENTS['plate_reader']}")
print(f"Read wavelength    : {ASSAY['wavelength_nm']} nm")
print(f"Ref wavelength     : {ASSAY['ref_wavelength_nm']} nm")

# --- Reader configuration ---
reader_config = {
    "instrument_id"     : INSTRUMENTS["plate_reader"],
    "protocol_file"     : "ELISA_TNFa_HSTA00E.ppr",
    "read_wavelength_nm": ASSAY["wavelength_nm"],
    "ref_wavelength_nm" : ASSAY["ref_wavelength_nm"],
    "read_mode"         : "Absorbance",
    "plate_type"        : "96-well_flat_bottom",
    "reads_per_well"    : 10,
    "read_time"         : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}

# --- OD ranges (R&D Systems HSTA00E typical data, page 8) ---
std_od_ranges = {
    "Standard_L1": (0.040, 0.055),   # 0.156 pg/mL
    "Standard_L2": (0.082, 0.096),   # 0.313 pg/mL
    "Standard_L3": (0.168, 0.184),   # 0.625 pg/mL
    "Standard_L4": (0.338, 0.358),   # 1.25  pg/mL
    "Standard_L5": (0.688, 0.708),   # 2.5   pg/mL
    "Standard_L6": (1.303, 1.323),   # 5.0   pg/mL
    "Standard_L7": (2.399, 2.419),   # 10.0  pg/mL
}

ctrl_od_ranges = {
    "Blank"           : (0.000, 0.050),
    "Negative Control": (0.050, 0.100),
    "Positive Control": (1.200, 1.800),
}

# Samples spread across mid-range OD (unknown concentrations)
sample_od_ranges = {
    f"Sample_{i:02d}": (base, base + 0.05)
    for i, base in enumerate(np.linspace(0.15, 1.80, 10), start=1)
}

def get_od_range(content, category):
    if category == "standard":
        return std_od_ranges.get(content, (0.05, 0.10))
    elif category == "control":
        return ctrl_od_ranges.get(content, (0.05, 0.10))
    elif category == "sample":
        return sample_od_ranges.get(content, (0.10, 0.15))
    return None

def simulate_od(od_range, instrument_noise=0.003):
    """
    Simulates single well OD reading with instrument noise.
    Noise model based on HSTA00E intra-assay CV of 1.9-2.2% (kit page 9).
    Net OD = signal(450nm) - reference(570nm).
    """
    if od_range is None:
        return 0.0
    low, high = od_range
    signal    = np.random.uniform(low, high)
    noise_450 = np.random.normal(0, instrument_noise)
    noise_570 = np.random.normal(0, instrument_noise * 0.5)
    return max(round(signal + noise_450 - noise_570, 4), 0.0)

# --- Execute plate read ---
print(f"\n[SoftMax] Initiating plate read — {reader_config['protocol_file']}")

wells_read    = 0
wells_flagged = []

for idx, row in plate_state_df.iterrows():
    if row["category"] == "empty":
        plate_state_df.at[idx, "od_value"] = 0.0
        plate_state_df.at[idx, "status"]   = "empty"
        continue

    od_range = get_od_range(row["content"], row["category"])
    od       = simulate_od(od_range)

    plate_state_df.at[idx, "od_value"]   = od
    plate_state_df.at[idx, "status"]     = "read_complete"
    plate_state_df.at[idx, "updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    if od_range is not None:
        low, high = od_range
        if not (low <= od <= high):
            plate_state_df.at[idx, "flagged"]     = True
            plate_state_df.at[idx, "flag_reason"] = (
                f"OD {od} outside expected range ({low}-{high})"
            )
            wells_flagged.append(row["well_id"])

    wells_read += 1

print(f"[SoftMax] Read complete — {wells_read} wells read, {len(wells_flagged)} flagged")
if wells_flagged:
    print(f"  Flagged wells: {wells_flagged}")

# --- Update plate_state.csv with OD values ---
plate_state_df.to_csv(plate_state_path, index=False)

# --- Preview ---
active = plate_state_df[plate_state_df["category"] != "empty"]
print(f"\nOD preview (first 12 active wells):")
print(active.head(12)[["well_id", "content", "category", "od_value", "flagged"]].to_string(index=False))

# --- Export raw_od_data.csv ---
active_df  = plate_state_df[plate_state_df["category"] != "empty"].copy()
od_records = []

for _, row in active_df.iterrows():
    od_records.append({
        "plate_id"   : flag["plate_id"],
        "well_id"    : row["well_id"],
        "content"    : row["content"],
        "category"   : row["category"],
        "od_value"   : row["od_value"],
        "flagged"    : row["flagged"],
        "flag_reason": row["flag_reason"],
        "wavelength" : reader_config["read_wavelength_nm"],
        "reference"  : reader_config["ref_wavelength_nm"],
        "read_time"  : reader_config["read_time"],
    })

od_df   = pd.DataFrame(od_records)
od_path = os.path.join(PATHS["data_output"], "raw_od_data.csv")
od_df.to_csv(od_path, index=False)

print(f"\nraw_od_data.csv -> {od_path}")
print(f"  Active wells  : {len(od_df)}")
print(f"  Flagged wells : {od_df['flagged'].sum()}")

print("\n=== OD Summary by Category ===")
for cat, group in od_df.groupby("category"):
    print(f"  {cat:<12}: mean={group['od_value'].mean():.4f}  "
          f"min={group['od_value'].min():.4f}  "
          f"max={group['od_value'].max():.4f}")

# --- Write softmax_complete.flag ---
softmax_flag_path = os.path.join(PATHS["flags"], "softmax_complete.flag")
with open(softmax_flag_path, "w") as f:
    json.dump({
        "status"         : "complete",
        "plate_id"       : flag["plate_id"],
        "raw_od_file"    : od_path,
        "wells_read"     : len(od_df),
        "wells_flagged"  : int(od_df["flagged"].sum()),
        "completed_at"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_instrument": "Data_Pipeline",
        "next_action"    : "parse_and_qc",
    }, f, indent=2)

print(f"\nsoftmax_complete.flag -> {softmax_flag_path}")
print("Next: data_pipeline.py")
