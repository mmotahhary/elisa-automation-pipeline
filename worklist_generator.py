"""
worklist_generator.py
Reads plate_map.csv and generates worklist.csv for the Hamilton simulator.
Run after assay_definition.py.
"""

import pandas as pd
import os
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS     = config["paths"]
PIPETTING = config["pipetting"]
ASSAY     = config["assay"]

# --- Load plate map ---
plate_map_path = os.path.join(PATHS["data_output"], "plate_map.csv")

if not os.path.exists(plate_map_path):
    raise FileNotFoundError("plate_map.csv not found. Run assay_definition.py first.")

plate_map_df = pd.read_csv(plate_map_path)
active_df    = plate_map_df[plate_map_df["category"] != "empty"].copy()

print(f"Plate map loaded: {len(plate_map_df)} total wells, {len(active_df)} active")

# --- Source positions on Hamilton deck ---
source_map = {
    "standard": "Position_2",
    "control" : "Position_4",
    "sample"  : "Position_3",
}

volume_map = {
    "standard": PIPETTING["standard_volume_ul"],
    "sample"  : PIPETTING["sample_volume_ul"],
    "control" : PIPETTING["control_volume_ul"],
}

# --- Build worklist ---
worklist = []
step_num = 1

# Pass 1: diluent to all active wells
for _, row in active_df.iterrows():
    worklist.append({
        "step"      : step_num,
        "action"    : "Dispense",
        "well_id"   : row["well_id"],
        "content"   : row["content"],
        "category"  : row["category"],
        "source"    : "Position_5",
        "volume_ul" : PIPETTING["diluent_volume_ul"],
        "tip_change": "No",
        "mix_after" : "No",
    })
    step_num += 1

# Pass 2: sample/standard/control to each well
for _, row in active_df.iterrows():
    source = source_map.get(row["category"])
    if source is None:
        continue

    worklist.append({
        "step"      : step_num,
        "action"    : "Aspirate+Dispense",
        "well_id"   : row["well_id"],
        "content"   : row["content"],
        "category"  : row["category"],
        "source"    : source,
        "volume_ul" : volume_map[row["category"]],
        "tip_change": "Yes",
        "mix_after" : "Yes",
    })
    step_num += 1

worklist_df = pd.DataFrame(worklist)

print(f"Worklist built: {len(worklist_df)} steps "
      f"({len(worklist_df[worklist_df['action'] == 'Dispense'])} diluent, "
      f"{len(worklist_df[worklist_df['action'] == 'Aspirate+Dispense'])} transfers)")

# --- Export worklist.csv ---
os.makedirs(PATHS["data_output"], exist_ok=True)
worklist_path = os.path.join(PATHS["data_output"], "worklist.csv")
worklist_df.to_csv(worklist_path, index=False)

# --- Export summary JSON ---
summary = {
    "plate_id"      : "PLATE_001",
    "assay"         : ASSAY["name"],
    "operator"      : "M. Motahhary",
    "created_at"    : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "total_steps"   : len(worklist_df),
    "active_wells"  : len(active_df),
    "worklist_file" : worklist_path,
    "next_step"     : "hamilton_simulator.py",
}

summary_path = os.path.join(PATHS["data_output"], "worklist_summary.json")
with open(summary_path, "w") as f:
    json.dump(summary, f, indent=2)

# --- Write handoff flag ---
os.makedirs(PATHS["flags"], exist_ok=True)
flag_path = os.path.join(PATHS["flags"], "worklist_ready.flag")
with open(flag_path, "w") as f:
    json.dump({
        "status"     : "ready",
        "plate_id"   : "PLATE_001",
        "worklist"   : worklist_path,
        "created_at" : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_action": "load_worklist_into_hamilton",
    }, f, indent=2)

print(f"\nworklist.csv        -> {worklist_path}")
print(f"worklist_summary.json -> {summary_path}")
print(f"worklist_ready.flag   -> {flag_path}")
print("Next: hamilton_simulator.py")
