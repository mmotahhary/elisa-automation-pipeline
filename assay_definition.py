"""
assay_definition.py
Builds the 96-well plate map from config and exports plate_map.csv.
Run this first — all downstream scripts depend on plate_map.csv.
"""

import pandas as pd
import os
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS = config["paths"]
ASSAY = config["assay"]

# --- Build well grid ---
rows  = list("ABCDEFGH")
cols  = list(range(1, 13))
wells = [f"{r}{c}" for r in rows for c in cols]

# --- Assign wells ---
plate_map  = {}
well_index = 0

def assign_wells(label, count=None):
    global well_index
    n = count if count is not None else ASSAY["replicates"]
    for _ in range(n):
        if well_index >= len(wells):
            raise ValueError(f"Plate full — cannot assign '{label}'")
        plate_map[wells[well_index]] = label
        well_index += 1

# Standards (L1–L7 + L0 zero standard)
for level in range(1, ASSAY["standard_levels"] + 1):
    assign_wells(f"Standard_L{level}")
assign_wells("Standard_L0")

# Controls
for ctrl in ASSAY["controls"]:
    assign_wells(ctrl)

# Samples
for s in range(1, ASSAY["n_samples"] + 1):
    assign_wells(f"Sample_{s:02d}")

# Fill remainder
while well_index < len(wells):
    plate_map[wells[well_index]] = "Empty"
    well_index += 1

# --- Categorize ---
def get_category(content):
    if content.startswith("Standard"):
        return "standard"
    elif content in ASSAY["controls"]:
        return "control"
    elif content.startswith("Sample"):
        return "sample"
    elif content == "Empty":
        return "empty"
    return "unknown"

# --- Build dataframe ---
records = []
for well, content in plate_map.items():
    records.append({
        "well_id"   : well,
        "row"       : well[0],
        "column"    : int(well[1:]),
        "content"   : content,
        "category"  : get_category(content),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

plate_map_df = pd.DataFrame(records)

# --- Print plate grid ---
plate_grid = pd.DataFrame(
    [[plate_map.get(f"{r}{c}", "") for c in cols] for r in rows],
    index=rows, columns=cols
)
print("=== 96-Well Plate Map ===\n")
print(plate_grid.to_string())

# --- Summary ---
print("\n=== Category Summary ===")
for cat, group in plate_map_df.groupby("category"):
    print(f"  {cat:<12}: {len(group)} wells")

# --- Export ---
os.makedirs(PATHS["data_output"], exist_ok=True)
out_path = os.path.join(PATHS["data_output"], "plate_map.csv")
plate_map_df.to_csv(out_path, index=False)

print(f"\nplate_map.csv saved to: {out_path}")
print("Next: worklist_generator.py")
