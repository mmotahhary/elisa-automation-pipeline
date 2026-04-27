"""
curve_fitting.py
Fits a 4PL standard curve to TNF-alpha ELISA standards and quantifies samples.
Reads parsed_standards.csv, parsed_samples.csv, and data_parsed.flag.
Outputs curve_params.json, final_results.csv, and curve_fitting_complete.flag.
Run after data_pipeline.py.
"""

import pandas as pd
import numpy as np
import os
import json
import warnings
from datetime import datetime
from scipy.optimize import curve_fit

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS                   = config["paths"]
QC                      = config["qc"]
STANDARD_CONCENTRATIONS = config["standard_concentrations"]
DILUTION_FACTOR         = config["assay"]["dilution_factor"]

# --- Check dependencies ---
flag_path = os.path.join(PATHS["flags"], "data_parsed.flag")

if not os.path.exists(flag_path):
    raise FileNotFoundError("data_parsed.flag not found. Run data_pipeline.py first.")

with open(flag_path) as f:
    flag = json.load(f)

if not flag["plate_passed_qc"]:
    raise RuntimeError("Plate failed QC — curve fitting not allowed. Investigate QC failure first.")

# --- Load standards ---
std_df = pd.read_csv(flag["parsed_standards"])

STANDARD_CONCENTRATIONS["Standard_L0"] = 0.0
std_df["concentration_pgml"] = std_df["content"].map(STANDARD_CONCENTRATIONS)

# Zero standard excluded from 4PL fit — used for blank correction only
std_fit_df = std_df[std_df["concentration_pgml"] > 0].copy()
std_fit_df = std_fit_df.sort_values("concentration_pgml").reset_index(drop=True)

print(f"Plate ID          : {flag['plate_id']}")
print(f"Standards loaded  : {len(std_df)} levels")
print(f"Used for 4PL fit  : {len(std_fit_df)} levels (zero standard excluded)")
print(f"Concentration range: {std_fit_df['concentration_pgml'].min()} - "
      f"{std_fit_df['concentration_pgml'].max()} pg/mL")

# --- 4PL model ---
def four_param_logistic(x, A, B, C, D):
    """
    4-Parameter Logistic (4PL) curve.
    A: minimum asymptote, B: Hill slope, C: EC50, D: maximum asymptote.
    Recommended by R&D Systems HSTA00E for TNF-alpha standard curve fitting.
    """
    return D + (A - D) / (1.0 + (x / C) ** B)

def inverse_4pl(od, A, B, C, D):
    """Converts OD back to concentration (pg/mL) using fitted 4PL parameters."""
    od = np.clip(od, A + 1e-6, D - 1e-6)
    return C * (((A - D) / (od - D) - 1.0) ** (1.0 / B))

# --- Fit curve ---
x_data = std_fit_df["concentration_pgml"].values.astype(float)
y_data = std_fit_df["mean_od"].values.astype(float)

p0     = [y_data.min(), 1.0, np.median(x_data), y_data.max()]
bounds = ([0, 0.1, 0.01, 0], [0.5, 10, 100, 3.5])

popt, _ = curve_fit(four_param_logistic, x_data, y_data,
                    p0=p0, bounds=bounds, maxfev=10000)
A, B, C, D = popt

# R²
y_predicted = four_param_logistic(x_data, A, B, C, D)
ss_res      = np.sum((y_data - y_predicted) ** 2)
ss_tot      = np.sum((y_data - np.mean(y_data)) ** 2)
r_squared   = 1 - (ss_res / ss_tot)
curve_accepted = r_squared >= QC["r2_threshold"]

print(f"\n=== 4PL Curve Parameters ===")
print(f"  A (min asymptote) : {A:.6f}")
print(f"  B (Hill slope)    : {B:.6f}")
print(f"  C (EC50)          : {C:.6f} pg/mL")
print(f"  D (max asymptote) : {D:.6f}")
print(f"  R²                : {r_squared:.6f}  "
      f"({'ACCEPTED' if curve_accepted else 'REJECTED — plate requires reanalysis'})")

# --- Save curve parameters ---
os.makedirs(PATHS["data_output"], exist_ok=True)
curve_params = {
    "plate_id"   : flag["plate_id"],
    "model"      : "4PL",
    "A"          : round(A, 6),
    "B"          : round(B, 6),
    "C"          : round(C, 6),
    "D"          : round(D, 6),
    "r_squared"  : round(r_squared, 6),
    "x_min_pgml" : float(x_data.min()),
    "x_max_pgml" : float(x_data.max()),
    "fit_accepted": curve_accepted,
    "fitted_at"  : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}

params_path = os.path.join(PATHS["data_output"], "curve_params.json")
with open(params_path, "w") as f:
    json.dump(curve_params, f, indent=2)

# --- Quantify samples ---
samp_df = pd.read_csv(flag["parsed_samples"])

od_at_min_std = four_param_logistic(x_data.min(), A, B, C, D)
od_at_max_std = four_param_logistic(x_data.max(), A, B, C, D)

print(f"\nQuantifiable OD range: {od_at_min_std:.4f} — {od_at_max_std:.4f}")

results = []

for _, row in samp_df.iterrows():
    mean_od = row["mean_od"]
    cv      = row["cv_pct"]

    if mean_od < od_at_min_std:
        conc, status = None, "BELOW_CURVE"
    elif mean_od > od_at_max_std:
        conc, status = None, "ABOVE_CURVE"
    else:
        conc   = round(inverse_4pl(mean_od, A, B, C, D), 3)
        status = "OK"
        if DILUTION_FACTOR > 1:
            conc = round(conc * DILUTION_FACTOR, 3)

    cv_flag = cv > QC["cv_threshold_pct"]

    results.append({
        "sample_id"         : row["content"],
        "mean_od"           : mean_od,
        "cv_pct"            : cv,
        "cv_flag"           : cv_flag,
        "concentration_pgml": conc,
        "status"            : status,
        "reportable"        : status == "OK" and not cv_flag,
        "dilution_factor"   : DILUTION_FACTOR,
    })

results_df = pd.DataFrame(results)

print(f"\n=== Sample Quantification Results ===")
print(f"{'Sample':<12} {'Mean OD':>10} {'CV%':>8} {'Conc (pg/mL)':>14} {'Status':>12} {'Reportable':>12}")
print("-" * 72)
for _, row in results_df.iterrows():
    conc = f"{row['concentration_pgml']:.3f}" if row["concentration_pgml"] else "N/A"
    print(f"{row['sample_id']:<12} {row['mean_od']:>10.4f} {row['cv_pct']:>8.2f} "
          f"{conc:>14} {row['status']:>12} {str(row['reportable']):>12}")

ok_count    = len(results_df[results_df["status"] == "OK"])
below_count = len(results_df[results_df["status"] == "BELOW_CURVE"])
above_count = len(results_df[results_df["status"] == "ABOVE_CURVE"])
cv_count    = results_df["cv_flag"].sum()

print(f"\n  Reportable  : {ok_count}   Below curve: {below_count}   "
      f"Above curve: {above_count}   CV flag: {cv_count}")

# --- Export final_results.csv ---
results_df["plate_id"]  = flag["plate_id"]
results_df["run_date"]  = datetime.now().strftime("%Y-%m-%d")
results_df["model"]     = curve_params["model"]
results_df["r_squared"] = curve_params["r_squared"]

results_path = os.path.join(PATHS["data_output"], "final_results.csv")
results_df.to_csv(results_path, index=False)

# --- Write curve_fitting_complete.flag ---
flag_out_path = os.path.join(PATHS["flags"], "curve_fitting_complete.flag")
with open(flag_out_path, "w") as f:
    json.dump({
        "status"      : "complete",
        "plate_id"    : flag["plate_id"],
        "final_results": results_path,
        "curve_params": params_path,
        "r_squared"   : curve_params["r_squared"],
        "fit_accepted": curve_params["fit_accepted"],
        "reportable"  : int(results_df["reportable"].sum()),
        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_action" : "generate_report",
    }, f, indent=2)

print(f"\nfinal_results.csv           -> {results_path}")
print(f"curve_params.json           -> {params_path}")
print(f"curve_fitting_complete.flag -> {flag_out_path}")
print("Next: reporting.py")
