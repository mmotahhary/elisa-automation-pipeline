"""
reporting.py
Generates standard curve plot, summary report CSV, and LIMS JSON payload.
Reads final_results.csv, curve_params.json, and curve_fitting_complete.flag.
Outputs standard_curve.png, summary_report.csv, results_payload.json,
pipeline_manifest.csv, and reporting_complete.flag.
Run after curve_fitting.py.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS                   = config["paths"]
ASSAY                   = config["assay"]
STANDARD_CONCENTRATIONS = config["standard_concentrations"]

# --- Check dependencies ---
flag_path = os.path.join(PATHS["flags"], "curve_fitting_complete.flag")

if not os.path.exists(flag_path):
    raise FileNotFoundError("curve_fitting_complete.flag not found. Run curve_fitting.py first.")

with open(flag_path) as f:
    flag = json.load(f)

results_df = pd.read_csv(flag["final_results"])

with open(flag["curve_params"]) as f:
    curve_params = json.load(f)

A  = curve_params["A"]
B  = curve_params["B"]
C  = curve_params["C"]
D  = curve_params["D"]
r2 = curve_params["r_squared"]

print(f"Plate ID   : {flag['plate_id']}")
print(f"R²         : {r2}")
print(f"Reportable : {flag['reportable']} samples")

# --- 4PL for plot ---
def four_param_logistic(x, A, B, C, D):
    return D + (A - D) / (1.0 + (x / C) ** B)

# --- Load standards for scatter plot ---
std_path = os.path.join(PATHS["data_output"], "parsed_standards.csv")
std_df   = pd.read_csv(std_path)

STANDARD_CONCENTRATIONS["Standard_L0"] = 0.0
std_df["concentration_pgml"] = std_df["content"].map(STANDARD_CONCENTRATIONS)
std_df = std_df[std_df["concentration_pgml"] > 0].sort_values("concentration_pgml")

# --- Generate standard curve plot ---
x_curve = np.logspace(
    np.log10(curve_params["x_min_pgml"] * 0.5),
    np.log10(curve_params["x_max_pgml"] * 1.5),
    300
)
y_curve = four_param_logistic(x_curve, A, B, C, D)

fig, ax = plt.subplots(figsize=(10, 6))
fig.patch.set_facecolor("#F8F9FA")
ax.set_facecolor("#F8F9FA")

ax.plot(x_curve, y_curve, color="#2E75B6", linewidth=2.5,
        label=f"4PL Fit (R²={r2:.4f})", zorder=3)

ax.scatter(std_df["concentration_pgml"], std_df["mean_od"],
           color="#1F4E79", s=80, zorder=5, marker="o", label="Standards")

for _, row in results_df.iterrows():
    if row["concentration_pgml"] is None or str(row["concentration_pgml"]) == "nan":
        continue
    color = "#2ECC71" if row["reportable"] else "#E74C3C"
    ax.scatter(row["concentration_pgml"], row["mean_od"],
               color=color, s=70, zorder=6, marker="D")

ax.axvspan(curve_params["x_min_pgml"], curve_params["x_max_pgml"],
           alpha=0.07, color="#2E75B6", label="Quantifiable range")

ax.set_xscale("log")
ax.set_xlabel("Concentration (pg/mL)", fontsize=12)
ax.set_ylabel("OD (450 nm)", fontsize=12)
ax.set_title(
    f"TNF-alpha ELISA — Standard Curve\n"
    f"Plate: {flag['plate_id']}  |  "
    f"Date: {datetime.now().strftime('%Y-%m-%d')}  |  "
    f"R²={r2:.4f}",
    fontsize=13, fontweight="bold", pad=15
)
ax.grid(True, which="both", linestyle="--", alpha=0.4)

legend_elements = [
    plt.Line2D([0], [0], color="#2E75B6", linewidth=2.5,
               label=f"4PL Fit (R²={r2:.4f})"),
    plt.scatter([], [], color="#1F4E79", s=80, marker="o", label="Standards"),
    mpatches.Patch(color="#2ECC71", label="Samples — Reportable"),
    mpatches.Patch(color="#E74C3C", label="Samples — Not Reportable"),
    mpatches.Patch(color="#2E75B6", alpha=0.2, label="Quantifiable Range"),
]
ax.legend(handles=legend_elements, loc="upper left", fontsize=9, framealpha=0.8)
plt.tight_layout()

os.makedirs(PATHS["reports"], exist_ok=True)
plot_path = os.path.join(PATHS["reports"], "standard_curve.png")
plt.savefig(plot_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"\nstandard_curve.png -> {plot_path}")

# --- Summary table ---
print(f"\n{'=' * 65}")
print(f"  FINAL REPORT — TNF-alpha ELISA")
print(f"  Plate ID  : {flag['plate_id']}")
print(f"  Date      : {datetime.now().strftime('%Y-%m-%d')}")
print(f"  Operator  : M. Motahhary")
print(f"  Protocol  : R&D Systems HSTA00E")
print(f"  Model     : {curve_params['model']}  |  R² = {r2}")
print(f"{'=' * 65}")
print(f"{'Sample':<12} {'Mean OD':>10} {'CV%':>8} {'Conc (pg/mL)':>14} {'Reportable':>12}")
print("-" * 65)

for _, row in results_df.iterrows():
    conc = f"{row['concentration_pgml']:.3f}" if row["concentration_pgml"] else "N/A"
    rep  = "YES" if row["reportable"] else "NO"
    print(f"{row['sample_id']:<12} {row['mean_od']:>10.4f} "
          f"{row['cv_pct']:>8.2f} {conc:>14} {rep:>12}")

print(f"{'=' * 65}")
print(f"  Reportable     : {results_df['reportable'].sum()} samples")
print(f"  Not reportable : {(~results_df['reportable']).sum()} samples")

# --- Export summary_report.csv ---
report_df = results_df.copy()
report_df["plate_id"]  = flag["plate_id"]
report_df["assay"]     = ASSAY["name"]
report_df["run_date"]  = datetime.now().strftime("%Y-%m-%d")
report_df["operator"]  = "M. Motahhary"
report_df["model"]     = curve_params["model"]
report_df["r_squared"] = r2
report_df["protocol"]  = "R&D Systems HSTA00E"

report_path = os.path.join(PATHS["reports"], "summary_report.csv")
report_df.to_csv(report_path, index=False)

# --- Build JSON payload for LIMS upload ---
payload = {
    "plate_id"   : flag["plate_id"],
    "assay"      : ASSAY["name"],
    "operator"   : "M. Motahhary",
    "run_date"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "protocol"   : "R&D Systems HSTA00E",
    "instrument" : config["instruments"]["plate_reader"],
    "model"      : curve_params["model"],
    "r_squared"  : r2,
    "curve_params": {"A": A, "B": B, "C": C, "D": D},
    "samples"    : [],
}

for _, row in results_df.iterrows():
    payload["samples"].append({
        "sample_id"         : row["sample_id"],
        "mean_od"           : row["mean_od"],
        "cv_pct"            : row["cv_pct"],
        "concentration_pgml": row["concentration_pgml"],
        "status"            : row["status"],
        "reportable"        : bool(row["reportable"]),
    })

payload_path = os.path.join(PATHS["reports"], "results_payload.json")
with open(payload_path, "w") as f:
    json.dump(payload, f, indent=2)

print(f"\nsummary_report.csv    -> {report_path}")
print(f"results_payload.json  -> {payload_path}")

# --- Write reporting_complete.flag ---
flag_out_path = os.path.join(PATHS["flags"], "reporting_complete.flag")
with open(flag_out_path, "w") as f:
    json.dump({
        "status"         : "complete",
        "plate_id"       : flag["plate_id"],
        "standard_curve" : plot_path,
        "summary_report" : report_path,
        "results_payload": payload_path,
        "completed_at"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_action"    : "lims_upload",
    }, f, indent=2)

# --- Pipeline manifest ---
manifest = [
    ("plate_map.csv",               PATHS["data_output"], "assay_definition"),
    ("worklist.csv",                PATHS["data_output"], "worklist_generator"),
    ("worklist_summary.json",       PATHS["data_output"], "worklist_generator"),
    ("plate_state.csv",             PATHS["data_output"], "plate_state"),
    ("plate_record.json",           PATHS["data_output"], "plate_state"),
    ("raw_od_data.csv",             PATHS["data_output"], "softmax_simulator"),
    ("parsed_standards.csv",        PATHS["data_output"], "data_pipeline"),
    ("parsed_controls.csv",         PATHS["data_output"], "data_pipeline"),
    ("parsed_samples.csv",          PATHS["data_output"], "data_pipeline"),
    ("qc_report.csv",               PATHS["data_output"], "data_pipeline"),
    ("curve_params.json",           PATHS["data_output"], "curve_fitting"),
    ("final_results.csv",           PATHS["data_output"], "curve_fitting"),
    ("standard_curve.png",          PATHS["reports"],     "reporting"),
    ("summary_report.csv",          PATHS["reports"],     "reporting"),
    ("results_payload.json",        PATHS["reports"],     "reporting"),
    ("worklist_ready.flag",         PATHS["flags"],       "worklist_generator"),
    ("plate_state_ready.flag",      PATHS["flags"],       "plate_state"),
    ("hamilton_complete.flag",      PATHS["flags"],       "hamilton_simulator"),
    ("softmax_complete.flag",       PATHS["flags"],       "softmax_simulator"),
    ("data_parsed.flag",            PATHS["flags"],       "data_pipeline"),
    ("curve_fitting_complete.flag", PATHS["flags"],       "curve_fitting"),
    ("reporting_complete.flag",     PATHS["flags"],       "reporting"),
    ("hamilton_action_log.csv",     PATHS["logs"],        "hamilton_simulator"),
]

print(f"\n{'=' * 65}")
print(f"  PIPELINE MANIFEST — {flag['plate_id']}")
print(f"{'=' * 65}")

manifest_records = []
all_present      = True

for fname, folder, source in manifest:
    path   = os.path.join(folder, fname)
    exists = os.path.exists(path)
    icon   = "OK" if exists else "MISSING"
    if not exists:
        all_present = False
    print(f"  [{icon:<7}] {fname:<40} <- {source}")
    manifest_records.append({
        "file"      : fname,
        "path"      : path,
        "source"    : source,
        "exists"    : exists,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

manifest_df   = pd.DataFrame(manifest_records)
manifest_path = os.path.join(PATHS["reports"], "pipeline_manifest.csv")
manifest_df.to_csv(manifest_path, index=False)

print(f"\n{'ALL FILES PRESENT' if all_present else 'WARNING: Some files missing'}")
print(f"pipeline_manifest.csv -> {manifest_path}")
print("Next: lims_upload.py")
