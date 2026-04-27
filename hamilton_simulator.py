"""
hamilton_simulator.py
Simulates Hamilton VENUS pipetting for a full ELISA run (R&D Systems HSTA00E).
Reads worklist.csv and plate_state_ready.flag.
Outputs hamilton_action_log.csv and hamilton_complete.flag.
Run after plate_state.py.
"""

import pandas as pd
import os
import json
import time
import random
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS         = config["paths"]
PIPETTING     = config["pipetting"]
INCUBATION    = config["incubation"]
INSTRUMENTS   = config["instruments"]
ERROR_ENABLED = config["simulation"]["error_simulation_enabled"]

# --- Check dependencies ---
worklist_path = os.path.join(PATHS["data_output"], "worklist.csv")
flag_path     = os.path.join(PATHS["flags"], "plate_state_ready.flag")

if not os.path.exists(worklist_path):
    raise FileNotFoundError("worklist.csv not found. Run worklist_generator.py first.")

if not os.path.exists(flag_path):
    raise FileNotFoundError("plate_state_ready.flag not found. Run plate_state.py first.")

worklist_df  = pd.read_csv(worklist_path)
active_wells = worklist_df["well_id"].unique().tolist()

with open(flag_path) as f:
    flag = json.load(f)

print(f"Worklist loaded : {len(worklist_df)} steps")
print(f"Active wells    : {len(active_wells)}")
print(f"Plate ID        : {flag['plate_id']}")

# --- Deck layout ---
deck = {
    "Position_1" : "Assay_Plate",
    "Position_2" : "Standards_Rack",
    "Position_3" : "Samples_Rack",
    "Position_4" : "Controls_Rack",
    "Position_5" : "Diluent_Reservoir",
    "Position_6" : "Wash_Buffer_Reservoir",
    "Position_7" : "Conjugate_Reservoir",
    "Position_8" : "Streptavidin_Reservoir",
    "Position_9" : "Substrate_Reservoir",
    "Position_10": "Stop_Solution_Reservoir",
    "Position_11": "Tip_Box_1",
    "Position_12": "Waste_Trough",
}

# --- Tip tracker ---
tip_tracker = {
    "tips_available" : 96,
    "tips_used"      : 0,
    "tip_changes"    : 0,
    "low_tip_warning": 16,
}

def pickup_tips(n=8):
    if tip_tracker["tips_available"] < n:
        tip_tracker["tips_available"] += 96
        print(f"  [Hamilton] Tip box replaced — 96 tips added")
    tip_tracker["tips_used"]      += n
    tip_tracker["tips_available"] -= n
    tip_tracker["tip_changes"]    += 1
    if tip_tracker["tips_available"] <= tip_tracker["low_tip_warning"]:
        print(f"  [Hamilton] WARNING: Low tips — {tip_tracker['tips_available']} remaining")

def drop_tips():
    pass  # tips consumed, no counter change needed

# --- Action log ---
action_log = []

def log_action(method, action, well, volume, source, status, note=""):
    action_log.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "method"   : method,
        "action"   : action,
        "well"     : well,
        "volume_ul": volume,
        "source"   : source,
        "status"   : status,
        "note"     : note,
    })

# --- Core pipetting ---
def aspirate(method, wells, vol, source):
    if not isinstance(wells, list):
        wells = [wells]
    for well in wells:
        log_action(method, "aspirate", well, vol, source, "OK")
    return True

def dispense(method, wells, vol, dest, mix_cycles=0, mix_volume=0):
    if not isinstance(wells, list):
        wells = [wells]
    for well in wells:
        log_action(method, "dispense", well, vol, dest, "OK")
    return True

def get_channel_groups(wells, channels=8):
    """Split well list into groups of 8 (Hamilton 8-channel head)."""
    return [wells[i:i + channels] for i in range(0, len(wells), channels)]

def pickup_tips_smart(n):
    pickup_tips(n)

# --- Wash cycle ---
def wash_cycle(method, wells, cycles=4, volume=400):
    print(f"\n  [Hamilton] Starting wash — {cycles} cycles, {volume}uL per well")
    for cycle in range(1, cycles + 1):
        print(f"  [Hamilton] Wash cycle {cycle}/{cycles}")
        for group in get_channel_groups(wells):
            pickup_tips_smart(len(group))
            for well in group:
                ok = aspirate(method, well, volume, "Waste_Trough")
                if not ok:
                    return False
                ok = dispense(method, well, volume, "Position_6")
                if not ok:
                    return False
            drop_tips()
            time.sleep(0.1)

    # Final aspirate — remove all residual wash buffer
    print(f"  [Hamilton] Final aspirate — removing wash buffer")
    for group in get_channel_groups(wells):
        pickup_tips_smart(len(group))
        for well in group:
            ok = aspirate(method, well, volume, "Waste_Trough")
            if not ok:
                return False
        drop_tips()

    print(f"  [Hamilton] Wash complete")
    return True

# --- VENUS method simulations ---

def method_add_diluent(wells):
    """Kit step 3: Add 50 uL Assay Diluent RD1-40 to each active well."""
    method = "ELISA_AddDiluent.med"
    vol    = PIPETTING["diluent_volume_ul"]
    print(f"\n[VENUS] Executing: {method} — {vol} uL x {len(wells)} wells")
    for group in get_channel_groups(wells):
        pickup_tips_smart(len(group))
        for well in group:
            ok = aspirate(method, well, vol, "Position_5")
            if not ok:
                return False
            ok = dispense(method, well, vol, "Assay_Plate")
            if not ok:
                return False
        drop_tips()
    print(f"[VENUS] {method} complete — {len(wells)} wells filled")
    return True

def method_add_samples(worklist_df):
    """Kit step 4: Add 50 uL sample/standard/control per well. Tip change every transfer."""
    method       = "ELISA_AddSamples.med"
    sample_steps = worklist_df[worklist_df["action"] == "Aspirate+Dispense"].copy()
    print(f"\n[VENUS] Executing: {method} — {len(sample_steps)} transfers, tip change per well")
    failed_wells = []
    for _, row in sample_steps.iterrows():
        pickup_tips_smart(1)
        ok = aspirate(method, row["well_id"], row["volume_ul"], row["source"])
        if not ok:
            failed_wells.append(row["well_id"])
            drop_tips()
            continue
        ok = dispense(method, row["well_id"], row["volume_ul"], "Assay_Plate",
                      mix_cycles=PIPETTING["mix_cycles"],
                      mix_volume=PIPETTING["mix_volume_ul"])
        if not ok:
            failed_wells.append(row["well_id"])
        drop_tips()
    if failed_wells:
        print(f"  [Hamilton] WARNING: {len(failed_wells)} wells failed: {failed_wells}")
    else:
        print(f"[VENUS] {method} complete — {len(sample_steps)} transfers done")
    return len(failed_wells) == 0

def method_add_conjugate(wells):
    """Kit step 6: Add 200 uL biotinylated detection antibody. No tip change needed."""
    method = "ELISA_AddConjugate.med"
    vol    = PIPETTING["conjugate_volume_ul"]
    print(f"\n[VENUS] Executing: {method} — {vol} uL x {len(wells)} wells")
    for group in get_channel_groups(wells):
        pickup_tips_smart(len(group))
        for well in group:
            ok = aspirate(method, well, vol, "Position_7")
            if not ok:
                return False
            ok = dispense(method, well, vol, "Assay_Plate")
            if not ok:
                return False
        drop_tips()
    print(f"[VENUS] {method} complete")
    return True

def method_add_streptavidin(wells):
    """Kit step 8: Add 200 uL Streptavidin Polymer-HRP (1X). No tip change needed."""
    method = "ELISA_AddStreptavidin.med"
    vol    = PIPETTING["streptavidin_volume_ul"]
    print(f"\n[VENUS] Executing: {method} — {vol} uL x {len(wells)} wells")
    for group in get_channel_groups(wells):
        pickup_tips_smart(len(group))
        for well in group:
            ok = aspirate(method, well, vol, "Position_8")
            if not ok:
                return False
            ok = dispense(method, well, vol, "Assay_Plate")
            if not ok:
                return False
        drop_tips()
    print(f"[VENUS] {method} complete")
    return True

def method_add_substrate(wells):
    """Kit step 10: Add 200 uL TMB substrate. Light-sensitive — dispense in well order."""
    method = "ELISA_AddSubstrate.med"
    vol    = PIPETTING["substrate_volume_ul"]
    print(f"\n[VENUS] Executing: {method} — {vol} uL x {len(wells)} wells (light sensitive)")
    for group in get_channel_groups(wells):
        pickup_tips_smart(len(group))
        for well in group:
            ok = aspirate(method, well, vol, "Position_9")
            if not ok:
                return False
            ok = dispense(method, well, vol, "Assay_Plate")
            if not ok:
                return False
        drop_tips()
    print(f"[VENUS] {method} complete — substrate added in well order")
    return True

def method_add_stop_solution(wells):
    """Kit step 11: Add 50 uL Stop Solution (2N H2SO4). Same order as substrate. Blue -> yellow."""
    method = "ELISA_AddStopSolution.med"
    vol    = PIPETTING["stop_volume_ul"]
    wells  = list(wells)  # preserve same order as substrate
    print(f"\n[VENUS] Executing: {method} — {vol} uL x {len(wells)} wells (CAUTION: 2N H2SO4)")
    for group in get_channel_groups(wells):
        pickup_tips_smart(len(group))
        for well in group:
            ok = aspirate(method, well, vol, "Position_10")
            if not ok:
                return False
            ok = dispense(method, group, vol, "Assay_Plate",
                          mix_cycles=2, mix_volume=vol * 0.8)
            if not ok:
                return False
        drop_tips()
    print(f"[VENUS] {method} complete — color should be yellow")
    return True

# --- Incubation simulator ---
def incubate(step_name, duration_sec, temp_c=25, simulate_sec=2):
    print(f"\n  [Incubator] {step_name}")
    print(f"    Real: {duration_sec // 60} min at {temp_c}C  |  Simulated: {simulate_sec}s")
    time.sleep(simulate_sec)
    print(f"  [Incubator] {step_name} complete")

# --- Plate status tracker ---
plate_status = {
    "plate_id"       : flag["plate_id"],
    "current_step"   : "initialized",
    "steps_completed": [],
    "failed_steps"   : [],
    "start_time"     : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}

def update_status(step_name, success=True):
    plate_status["current_step"] = step_name
    if success:
        plate_status["steps_completed"].append(step_name)
        print(f"\n  [GBG] Step complete : {step_name}")
    else:
        plate_status["failed_steps"].append(step_name)
        print(f"\n  [GBG] Step FAILED   : {step_name}")
    return success

# --- Full ELISA run ---
def run_elisa_protocol():
    """
    Executes full ELISA protocol in kit order (HSTA00E steps 3-11).
    Mirrors Green Button Go orchestration logic.
    """
    tip_tracker["tips_available"] = 96
    tip_tracker["tips_used"]      = 0
    tip_tracker["tip_changes"]    = 0

    print("=" * 55)
    print("  HAMILTON SIMULATOR — FULL ELISA RUN")
    print(f"  Plate    : {plate_status['plate_id']}")
    print(f"  Start    : {plate_status['start_time']}")
    print(f"  Protocol : R&D Systems HSTA00E")
    print("=" * 55)

    wells = active_wells

    # Kit step 3
    print("\n[Kit Step 3] Add Assay Diluent")
    ok = method_add_diluent(wells)
    if not update_status("add_diluent", ok):
        return False

    # Kit step 4
    print("\n[Kit Step 4] Add Samples / Standards / Controls")
    ok = method_add_samples(worklist_df)
    if not update_status("add_samples", ok):
        return False
    incubate("Sample incubation",
             duration_sec=INCUBATION["sample_sec"],
             temp_c=INCUBATION["sample_temp_c"])

    # Kit step 5
    print("\n[Kit Step 5] Wash x4")
    ok = wash_cycle("ELISA_Wash.med", wells,
                    cycles=PIPETTING["wash_cycles"],
                    volume=PIPETTING["wash_volume_ul"])
    if not update_status("wash_1", ok):
        return False

    # Kit step 6
    print("\n[Kit Step 6] Add Conjugate")
    ok = method_add_conjugate(wells)
    if not update_status("add_conjugate", ok):
        return False
    incubate("Conjugate incubation",
             duration_sec=INCUBATION["detection_antibody_sec"],
             temp_c=INCUBATION["detection_temp_c"])

    # Kit step 7
    print("\n[Kit Step 7] Wash x4")
    ok = wash_cycle("ELISA_Wash.med", wells,
                    cycles=PIPETTING["wash_cycles"],
                    volume=PIPETTING["wash_volume_ul"])
    if not update_status("wash_2", ok):
        return False

    # Kit step 8
    print("\n[Kit Step 8] Add Streptavidin-HRP")
    ok = method_add_streptavidin(wells)
    if not update_status("add_streptavidin", ok):
        return False
    incubate("Streptavidin incubation",
             duration_sec=INCUBATION["streptavidin_sec"],
             temp_c=INCUBATION["detection_temp_c"])

    # Kit step 9
    print("\n[Kit Step 9] Wash x4")
    ok = wash_cycle("ELISA_Wash.med", wells,
                    cycles=PIPETTING["wash_cycles"],
                    volume=PIPETTING["wash_volume_ul"])
    if not update_status("wash_3", ok):
        return False

    # Kit step 10
    print("\n[Kit Step 10] Add Substrate Solution")
    ok = method_add_substrate(wells)
    if not update_status("add_substrate", ok):
        return False
    incubate("Substrate incubation — protect from light",
             duration_sec=INCUBATION["substrate_sec"],
             temp_c=INCUBATION["substrate_temp_c"])

    # Kit step 11
    print("\n[Kit Step 11] Add Stop Solution")
    ok = method_add_stop_solution(wells)
    if not update_status("add_stop_solution", ok):
        return False

    print("\n" + "=" * 55)
    print("  HAMILTON RUN COMPLETE")
    print(f"  Steps completed : {len(plate_status['steps_completed'])}")
    print(f"  Steps failed    : {len(plate_status['failed_steps'])}")
    print(f"  Tips used       : {tip_tracker['tips_used']}")
    print(f"  Tip changes     : {tip_tracker['tip_changes']}")
    print("=" * 55)
    return True

# --- Execute ---
run_success = run_elisa_protocol()

# --- Export action log ---
os.makedirs(PATHS["logs"], exist_ok=True)
action_log_df   = pd.DataFrame(action_log)
action_log_path = os.path.join(PATHS["logs"], "hamilton_action_log.csv")
action_log_df.to_csv(action_log_path, index=False)

print(f"\nAction log: {len(action_log_df)} entries -> {action_log_path}")

if "status" in action_log_df.columns:
    for status, count in action_log_df["status"].value_counts().items():
        print(f"  {status}: {count}")

if "method" in action_log_df.columns:
    for method, group in action_log_df.groupby("method"):
        print(f"  {method}: {len(group)} actions")

# --- Write completion flag ---
flag_out_path = os.path.join(PATHS["flags"], "hamilton_complete.flag")
flag_content  = {
    "status"          : "complete" if run_success else "failed",
    "plate_id"        : plate_status["plate_id"],
    "protocol"        : "HSTA00E",
    "completed_at"    : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "steps_completed" : plate_status["steps_completed"],
    "failed_steps"    : plate_status["failed_steps"],
    "tips_used"       : tip_tracker["tips_used"],
    "action_log"      : action_log_path,
    "next_instrument" : "SoftMax_Pro_Reader_01",
    "next_action"     : "move_plate_to_reader",
}

with open(flag_out_path, "w") as f:
    json.dump(flag_content, f, indent=2)

print(f"\nhamiltom_complete.flag -> {flag_out_path} [{flag_content['status']}]")

if run_success:
    print(f"\n  [GBG] Move {plate_status['plate_id']}: Hamilton deck -> SoftMax Pro nest")
    print("  Plate ready for reading (Kit Step 12)")
    print("  Next: softmax_simulator.py")
else:
    print("\n  [GBG] Run failed — check hamilton_action_log.csv")
