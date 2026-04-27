"""
plate_state.py
Builds the plate state object from plate_map.csv and exports plate_state.csv.
Run after worklist_generator.py.
"""

import pandas as pd
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

# --- Check dependencies ---
plate_map_path = os.path.join(PATHS["data_output"], "plate_map.csv")
flag_path      = os.path.join(PATHS["flags"], "worklist_ready.flag")

if not os.path.exists(plate_map_path):
    raise FileNotFoundError("plate_map.csv not found. Run assay_definition.py first.")

if not os.path.exists(flag_path):
    raise FileNotFoundError("worklist_ready.flag not found. Run worklist_generator.py first.")

plate_map_df = pd.read_csv(plate_map_path)

with open(flag_path) as f:
    flag = json.load(f)

print(f"Plate map loaded : {len(plate_map_df)} wells")
print(f"Worklist status  : {flag['status']}")
print(f"Plate ID         : {flag['plate_id']}")

# --- Expected OD ranges per content type (from HSTA00E kit) ---
content_profiles = {
    "Standard_L0"    : {"expected_od_range": (0.000, 0.010), "category": "standard"},
    "Standard_L1"    : {"expected_od_range": (0.040, 0.055), "category": "standard"},
    "Standard_L2"    : {"expected_od_range": (0.082, 0.096), "category": "standard"},
    "Standard_L3"    : {"expected_od_range": (0.168, 0.184), "category": "standard"},
    "Standard_L4"    : {"expected_od_range": (0.338, 0.358), "category": "standard"},
    "Standard_L5"    : {"expected_od_range": (0.688, 0.708), "category": "standard"},
    "Standard_L6"    : {"expected_od_range": (1.303, 1.323), "category": "standard"},
    "Standard_L7"    : {"expected_od_range": (2.399, 2.419), "category": "standard"},
    "Blank"          : {"expected_od_range": (0.000, 0.050), "category": "control"},
    "Negative Control": {"expected_od_range": (0.050, 0.100), "category": "control"},
    "Positive Control": {"expected_od_range": (1.200, 1.800), "category": "control"},
}

for i in range(1, ASSAY["n_samples"] + 1):
    content_profiles[f"Sample_{i:02d}"] = {
        "expected_od_range": (0.100, 2.000),
        "category"         : "sample",
    }

# --- Build plate state ---
plate_state = []

for _, row in plate_map_df.iterrows():
    content = row["content"]
    profile = content_profiles.get(content, {})

    plate_state.append({
        "well_id"    : row["well_id"],
        "row"        : row["row"],
        "column"     : row["column"],
        "content"    : content,
        "category"   : row["category"],
        "od_range"   : str(profile.get("expected_od_range")),
        "od_value"   : None,
        "flagged"    : False,
        "flag_reason": "",
        "status"     : "pending_read",
        "location"   : INSTRUMENTS["hamilton"],
        "updated_at" : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

plate_state_df = pd.DataFrame(plate_state)

print("\n=== Plate State Summary ===")
for cat, group in plate_state_df.groupby("category"):
    print(f"  {cat:<12}: {len(group)} wells")

# --- Export plate_state.csv ---
os.makedirs(PATHS["data_output"], exist_ok=True)
plate_state_path = os.path.join(PATHS["data_output"], "plate_state.csv")
plate_state_df.to_csv(plate_state_path, index=False)

# --- Export plate_record.json ---
plate_record = {
    "plate_id"        : flag["plate_id"],
    "barcode"         : "ELI-2026-001",
    "assay"           : ASSAY["name"],
    "operator"        : "M. Motahhary",
    "sample_type"     : ASSAY["sample_type"],
    "created_at"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "status"          : "in_progress",
    "current_location": INSTRUMENTS["hamilton"],
    "protocol"        : "HSTA00E",
    "worklist_file"   : flag["worklist"],
    "plate_state_file": plate_state_path,
    "steps_complete"  : [],
}

plate_record_path = os.path.join(PATHS["data_output"], "plate_record.json")
with open(plate_record_path, "w") as f:
    json.dump(plate_record, f, indent=2)

# --- Write handoff flag ---
flag_out_path = os.path.join(PATHS["flags"], "plate_state_ready.flag")
with open(flag_out_path, "w") as f:
    json.dump({
        "status"          : "ready",
        "plate_id"        : plate_record["plate_id"],
        "plate_state_file": plate_state_path,
        "plate_record"    : plate_record_path,
        "created_at"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_action"     : "begin_hamilton_run",
    }, f, indent=2)

print(f"\nplate_state.csv        -> {plate_state_path}")
print(f"plate_record.json      -> {plate_record_path}")
print(f"plate_state_ready.flag -> {flag_out_path}")
print("Next: hamilton_simulator.py")
