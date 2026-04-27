"""
lims_upload.py
Simulates REST API upload of results to a LIMS endpoint.
Includes retry logic and mock server for testing.
Reads results_payload.json and reporting_complete.flag.
Outputs lims_confirmation.json (or lims_upload_error.json on failure)
and pipeline_complete.flag.
Run after reporting.py.

To use with a real LIMS endpoint:
  - Set mock_status_code = None (or remove the mock patch block)
  - Ensure config["lims"]["endpoint"] and ["api_key"] are correct
"""

import json
import os
import time
import requests
from datetime import datetime
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS = config["paths"]
LIMS  = config["lims"]

# --- Check dependencies ---
flag_path = os.path.join(PATHS["flags"], "reporting_complete.flag")

if not os.path.exists(flag_path):
    raise FileNotFoundError("reporting_complete.flag not found. Run reporting.py first.")

with open(flag_path) as f:
    flag = json.load(f)

payload_path = flag["results_payload"]

if not os.path.exists(payload_path):
    raise FileNotFoundError(f"results_payload.json not found: {payload_path}")

with open(payload_path) as f:
    payload = json.load(f)

print(f"Plate ID      : {flag['plate_id']}")
print(f"Endpoint      : {LIMS['endpoint']}")
print(f"Samples       : {len(payload['samples'])}")

# --- Upload function ---
def upload_to_lims(payload, config):
    """
    Posts results payload to LIMS REST endpoint with retry logic.
    Returns: (success, response_data, status_code)
    For production use: remove the mock patch in the execution block below.
    """
    headers = {
        "Content-Type" : "application/json",
        "Authorization": f"Bearer {config['api_key']}",
        "X-Lab-Source" : "ELISA-Pipeline-v1",
    }

    attempt = 0
    while attempt < config["max_retries"]:
        attempt += 1
        print(f"  [LIMS] Upload attempt {attempt}/{config['max_retries']}...")
        try:
            response = requests.post(
                config["endpoint"],
                headers=headers,
                json=payload,
                timeout=config["timeout"],
            )

            if response.status_code == 200:
                return True, response.json(), response.status_code

            elif response.status_code in [400, 422]:
                print(f"  [LIMS] Payload error {response.status_code} — not retrying")
                return False, {"error": response.text}, response.status_code

            else:
                print(f"  [LIMS] Server error {response.status_code} — retrying")
                time.sleep(config["retry_delay"])

        except requests.exceptions.Timeout:
            print(f"  [LIMS] Timeout on attempt {attempt}")
            time.sleep(config["retry_delay"])

        except requests.exceptions.ConnectionError:
            print(f"  [LIMS] Connection error on attempt {attempt}")
            time.sleep(config["retry_delay"])

    return False, {"error": "Max retries exceeded"}, 0

# --- Mock LIMS server ---
# Change mock_status_code to test different scenarios:
#   200 = success
#   500 = server error (triggers retry)
#   400 = bad payload (no retry)
mock_status_code = 200

def build_mock_response(status_code, payload):
    mock = MagicMock()
    mock.status_code = status_code
    if status_code == 200:
        mock.json.return_value = {
            "status"         : "success",
            "lims_record_id" : f"LIMS-{payload['plate_id']}-"
                               f"{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "samples_written": len(payload["samples"]),
            "timestamp"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    else:
        mock.text = f"Simulated server error {status_code}"
        mock.json.return_value = {"error": mock.text}
    return mock

# --- Execute upload ---
print(f"\n[LIMS] Uploading {len(payload['samples'])} samples to {LIMS['endpoint']}")

with patch("requests.post") as mock_post:
    mock_post.return_value = build_mock_response(mock_status_code, payload)
    success, response_data, status_code = upload_to_lims(payload, LIMS)

# --- Handle response ---
os.makedirs(PATHS["reports"], exist_ok=True)

if success:
    confirmation = {
        "upload_status"  : "success",
        "lims_record_id" : response_data["lims_record_id"],
        "http_status"    : status_code,
        "uploaded_at"    : response_data["timestamp"],
        "plate_id"       : payload["plate_id"],
        "samples_written": response_data["samples_written"],
        "endpoint"       : LIMS["endpoint"],
    }

    confirm_path = os.path.join(PATHS["reports"], "lims_confirmation.json")
    with open(confirm_path, "w") as f:
        json.dump(confirmation, f, indent=2)

    print(f"\n[LIMS] Upload successful — HTTP {status_code}")
    print(f"  LIMS Record ID  : {response_data['lims_record_id']}")
    print(f"  Samples written : {response_data['samples_written']}")
    print(f"\nlims_confirmation.json -> {confirm_path}")

else:
    error_report = {
        "upload_status"  : "failed",
        "http_status"    : status_code,
        "error"          : response_data.get("error"),
        "failed_at"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "plate_id"       : payload["plate_id"],
        "action_required": "Investigate LIMS connectivity and resubmit",
        "payload_file"   : payload_path,
    }

    error_path = os.path.join(PATHS["reports"], "lims_upload_error.json")
    with open(error_path, "w") as f:
        json.dump(error_report, f, indent=2)

    print(f"\n[LIMS] Upload failed — HTTP {status_code}")
    print(f"  Reason: {response_data.get('error')}")
    print(f"lims_upload_error.json -> {error_path}")

# --- Write pipeline_complete.flag ---
if success:
    final_flag_path = os.path.join(PATHS["flags"], "pipeline_complete.flag")
    with open(final_flag_path, "w") as f:
        json.dump({
            "status"         : "archived",
            "plate_id"       : payload["plate_id"],
            "assay"          : payload["assay"],
            "operator"       : payload["operator"],
            "run_date"       : payload["run_date"],
            "lims_record_id" : confirmation["lims_record_id"],
            "samples_written": confirmation["samples_written"],
            "completed_at"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2)

    print(f"\n{'=' * 65}")
    print(f"  ELISA AUTOMATION PIPELINE — COMPLETE")
    print(f"{'=' * 65}")
    print(f"  Plate ID    : {payload['plate_id']}")
    print(f"  Assay       : {payload['assay']}")
    print(f"  Operator    : {payload['operator']}")
    print(f"  Run date    : {payload['run_date']}")
    print(f"  LIMS Record : {confirmation['lims_record_id']}")
    print(f"  Samples     : {confirmation['samples_written']}")
    print(f"{'=' * 65}")

    key_outputs = [
        ("plate_map.csv",          PATHS["data_output"]),
        ("worklist.csv",           PATHS["data_output"]),
        ("plate_state.csv",        PATHS["data_output"]),
        ("raw_od_data.csv",        PATHS["data_output"]),
        ("qc_report.csv",          PATHS["data_output"]),
        ("curve_params.json",      PATHS["data_output"]),
        ("final_results.csv",      PATHS["data_output"]),
        ("standard_curve.png",     PATHS["reports"]),
        ("summary_report.csv",     PATHS["reports"]),
        ("results_payload.json",   PATHS["reports"]),
        ("lims_confirmation.json", PATHS["reports"]),
        ("hamilton_action_log.csv",PATHS["logs"]),
    ]

    all_present = True
    print(f"\n=== Output Files ===")
    for fname, folder in key_outputs:
        path   = os.path.join(folder, fname)
        exists = os.path.exists(path)
        if not exists:
            all_present = False
        print(f"  [{'OK' if exists else 'MISSING'}] {fname}")

    print(f"\n{'ALL FILES PRESENT' if all_present else 'WARNING: Some files missing'}")
