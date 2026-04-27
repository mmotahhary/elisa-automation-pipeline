"""
data_pipeline.py
Parses raw OD data, runs plate QC checks, and exports group CSVs.
Reads raw_od_data.csv and softmax_complete.flag.
Outputs parsed_standards.csv, parsed_controls.csv, parsed_samples.csv,
qc_report.csv, and data_parsed.flag.
Run after softmax_simulator.py.
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

PATHS = config["paths"]
ASSAY = config["assay"]
QC    = config["qc"]

# --- Check dependencies ---
flag_path = os.path.join(PATHS["flags"], "softmax_complete.flag")

if not os.path.exists(flag_path):
    raise FileNotFoundError("softmax_complete.flag not found. Run softmax_simulator.py first.")

with open(flag_path) as f:
    flag = json.load(f)

od_path = flag["raw_od_file"]

if not os.path.exists(od_path):
    raise FileNotFoundError(f"raw_od_data.csv not found: {od_path}")

raw_df = pd.read_csv(od_path)

required_columns = {"plate_id", "well_id", "content", "category", "od_value", "flagged"}
missing = required_columns - set(raw_df.columns)
if missing:
    raise ValueError(f"Missing columns in raw_od_data.csv: {missing}")

print(f"Plate ID      : {flag['plate_id']}")
print(f"Wells loaded  : {len(raw_df)}")
print(f"Wells flagged : {raw_df['flagged'].sum()}")

# --- Separate by group ---
standards_df = raw_df[raw_df["category"] == "standard"].copy()
controls_df  = raw_df[raw_df["category"] == "control"].copy()
samples_df   = raw_df[raw_df["category"] == "sample"].copy()

print(f"\nStandards : {len(standards_df)} wells")
print(f"Controls  : {len(controls_df)} wells")
print(f"Samples   : {len(samples_df)} wells")

# --- Replicate statistics ---
def calculate_replicate_stats(df, group_col="content"):
    """Mean OD, SD, CV% per replicate group."""
    results = []
    for label, group in df.groupby(group_col):
        od_values = group["od_value"].values
        mean_od   = np.mean(od_values)
        sd_od     = np.std(od_values, ddof=1) if len(od_values) > 1 else 0.0
        cv_pct    = (sd_od / mean_od * 100) if mean_od > 0 else 0.0
        results.append({
            "content"      : label,
            "category"     : group["category"].iloc[0],
            "n_replicates" : len(od_values),
            "od_values"    : list(np.round(od_values, 4)),
            "mean_od"      : round(mean_od, 4),
            "sd_od"        : round(sd_od, 4),
            "cv_pct"       : round(cv_pct, 2),
            "n_flagged"    : int(group["flagged"].sum()),
        })
    return pd.DataFrame(results)

std_stats  = calculate_replicate_stats(standards_df)
ctrl_stats = calculate_replicate_stats(controls_df)
samp_stats = calculate_replicate_stats(samples_df)

print("\n=== Standards ===")
print(std_stats[["content", "mean_od", "sd_od", "cv_pct", "n_flagged"]].to_string(index=False))
print("\n=== Controls ===")
print(ctrl_stats[["content", "mean_od", "sd_od", "cv_pct", "n_flagged"]].to_string(index=False))
print("\n=== Samples ===")
print(samp_stats[["content", "mean_od", "sd_od", "cv_pct", "n_flagged"]].to_string(index=False))

# --- Plate QC gate ---
# ICH M10: CV% < 15% for standards, < 20% for samples.
# CV% check is skipped for near-zero OD (noise floor artifact).
CV_OD_MINIMUM = 0.05

qc_results   = []
plate_passed = True

for _, row in ctrl_stats.iterrows():
    content = row["content"]
    mean_od = row["mean_od"]
    cv      = row["cv_pct"]
    passed  = True
    reasons = []

    if content == "Blank":
        if mean_od > QC["blank_max_od"]:
            passed = False
            reasons.append(f"Blank OD {mean_od} > max {QC['blank_max_od']}")

    if content == "Negative Control":
        if mean_od > QC["neg_ctrl_max_od"]:
            passed = False
            reasons.append(f"Neg Ctrl OD {mean_od} > max {QC['neg_ctrl_max_od']}")

    if content == "Positive Control":
        if mean_od < QC["pos_ctrl_min_od"]:
            passed = False
            reasons.append(f"Pos Ctrl OD {mean_od} < min {QC['pos_ctrl_min_od']}")

    if mean_od >= CV_OD_MINIMUM:
        if cv > QC["cv_threshold_pct"]:
            passed = False
            reasons.append(f"CV% {cv} > threshold {QC['cv_threshold_pct']}")
    else:
        reasons.append(f"CV% skipped — OD {mean_od} below noise floor ({CV_OD_MINIMUM})")

    if not passed:
        plate_passed = False

    qc_results.append({
        "content": content,
        "mean_od": mean_od,
        "cv_pct" : cv,
        "passed" : passed,
        "reason" : "; ".join(reasons) if reasons else "OK",
    })

qc_df = pd.DataFrame(qc_results)

print("\n=== Plate QC Report ===")
print(qc_df.to_string(index=False))

if not plate_passed:
    print("\n[Pipeline] PLATE FAILED QC — investigation required before reanalysis")
else:
    print("\n[Pipeline] Plate passed QC")

# --- Export parsed CSVs ---
os.makedirs(PATHS["data_output"], exist_ok=True)

std_path  = os.path.join(PATHS["data_output"], "parsed_standards.csv")
ctrl_path = os.path.join(PATHS["data_output"], "parsed_controls.csv")
samp_path = os.path.join(PATHS["data_output"], "parsed_samples.csv")
qc_path   = os.path.join(PATHS["data_output"], "qc_report.csv")

std_stats.to_csv(std_path,   index=False)
ctrl_stats.to_csv(ctrl_path, index=False)
samp_stats.to_csv(samp_path, index=False)
qc_df.to_csv(qc_path,        index=False)

print(f"\nparsed_standards.csv -> {std_path}")
print(f"parsed_controls.csv  -> {ctrl_path}")
print(f"parsed_samples.csv   -> {samp_path}")
print(f"qc_report.csv        -> {qc_path}")

# --- Write data_parsed.flag ---
flag_out_path = os.path.join(PATHS["flags"], "data_parsed.flag")
with open(flag_out_path, "w") as f:
    json.dump({
        "status"          : "complete",
        "plate_id"        : flag["plate_id"],
        "plate_passed_qc" : plate_passed,
        "parsed_standards": std_path,
        "parsed_controls" : ctrl_path,
        "parsed_samples"  : samp_path,
        "qc_report"       : qc_path,
        "completed_at"    : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_action"     : "curve_fitting",
    }, f, indent=2)

print(f"\ndata_parsed.flag -> {flag_out_path}")
print("Next: curve_fitting.py")
