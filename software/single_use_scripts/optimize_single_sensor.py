import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear


# config
TUNING_DATE_TAG = "2026_02_20"        # BiosigNULL/tuning/<tag>/
EMPTY_ROOM_DATE_TAG = "2026_02_24"   # BiosigNULL/raw_data/<tag>/empty_room.txt
COIL_CONFIG_DATE_TAG = "2026_02_24"  # BiosigNULL/coil_configs/<tag>/

# optimize these sesnors
SENSOR_IDS = list(range(1, 14))

# Desired field at each sensor (nT)
TARGET_BX = 0.0
TARGET_BY = 0.0
TARGET_BZ = 0.0

# Stop when ALL components are within this tolerance (nT)
TOL_NT = 0.1

V_MAX = 15.0  # max voltage (V)
W_BX, W_BY, W_BZ = 1.0, 1.0, 10.0  # weights 

# maximum selection of coils
MAX_COILS_TO_USE = None  # none uses all

COILS = [
    "r1", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "r16", "c2", "c3"
]
TUNING_STATS_FILENAME = "{coil} tuning curves_stats.csv"



# Locate BiosigNULL base dir


SCRIPT_DIR = Path(__file__).resolve().parent

BASE_DIR = None
for p in [SCRIPT_DIR, *SCRIPT_DIR.parents]:
    name = p.name.lower()
    if name == "biosignull" or name.startswith("biosignull_"):
        BASE_DIR = p
        break

if BASE_DIR is None:
    raise RuntimeError(f"Error: Script dir is: {SCRIPT_DIR}")



# Pathing


COIL_CONFIG_DIR = BASE_DIR / "coil_configs" / COIL_CONFIG_DATE_TAG
COIL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

TUNING_DIR = BASE_DIR / "tuning" / TUNING_DATE_TAG
EMPTY_ROOM_PATH = BASE_DIR / "raw_data" / EMPTY_ROOM_DATE_TAG / "trial1OFF.txt"



def load_empty_room_sensor_field(empty_room_path: Path, sensor_id: int) -> np.ndarray:
    empty = pd.read_csv(
        empty_room_path,
        header=None,
        names=["sensor", "tag", "Bx", "By", "Bz"],
        engine="python",
        skip_blank_lines=True,
        na_values=["---", "--", "-"],
    )

    empty["sensor"] = empty["sensor"].astype(str).str.strip()
    empty = empty[empty["sensor"].str.contains(":")]
    empty["sensor_id"] = pd.to_numeric(empty["sensor"].str.split(":").str[-1], errors="coerce")
    empty = empty[empty["sensor_id"].between(1, 13)].copy()

    for c in ["Bx", "By", "Bz"]:
        empty[c] = pd.to_numeric(empty[c], errors="coerce")

    empty = empty.dropna(subset=["sensor_id", "Bx", "By", "Bz"]).copy()
    empty["sensor_id"] = empty["sensor_id"].astype(int)

    row = empty.loc[empty["sensor_id"] == int(sensor_id)]
    if row.empty:
        raise ValueError(f"Sensor {sensor_id} not found in empty_room.txt: {empty_room_path}")

    bx = float(row["Bx"].iloc[0])
    by = float(row["By"].iloc[0])
    bz = float(row["Bz"].iloc[0])
    return np.array([bx, by, bz], dtype=float)


def load_coil_slopes_for_sensor(stats_csv: Path, sensor_id: int) -> np.ndarray:
    df = pd.read_csv(stats_csv)

    required = {"sensor_id", "component", "slope_per_V"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{stats_csv} missing required columns: {sorted(missing)}")

    df["sensor_id"] = pd.to_numeric(df["sensor_id"], errors="coerce")
    df["component"] = df["component"].astype(str).str.strip()
    df["slope_per_V"] = pd.to_numeric(df["slope_per_V"], errors="coerce")
    df = df.dropna(subset=["sensor_id", "component", "slope_per_V"]).copy()
    df["sensor_id"] = df["sensor_id"].astype(int)

    df = df[df["sensor_id"] == int(sensor_id)]
    df = df[df["component"].isin(["Bx", "By", "Bz"])]

    # default 0 if missing
    sBx = float(df.loc[df["component"] == "Bx", "slope_per_V"].mean()) if (df["component"] == "Bx").any() else 0.0
    sBy = float(df.loc[df["component"] == "By", "slope_per_V"].mean()) if (df["component"] == "By").any() else 0.0
    sBz = float(df.loc[df["component"] == "Bz", "slope_per_V"].mean()) if (df["component"] == "Bz").any() else 0.0

    return np.array([sBx, sBy, sBz], dtype=float)


w = np.array([np.sqrt(W_BX), np.sqrt(W_BY), np.sqrt(W_BZ)], dtype=float)  # (3,)

def within_tol(residual_vec: np.ndarray, tgt: np.ndarray, tol: float) -> bool:
    return bool(np.all(np.abs(residual_vec - tgt) <= tol))


def score_error(residual_vec: np.ndarray, tgt: np.ndarray) -> float:
    # prioritize worst component error, then weighted L2
    e = residual_vec - tgt
    return float(np.max(np.abs(e)) * 1e3 + np.linalg.norm(e * w))


def solve_subset(A_subset: np.ndarray, b0_vec: np.ndarray, tgt: np.ndarray) -> np.ndarray:
    # minimize the cost func (v*a -B)*weights
    Aw = A_subset * w[:, None]
    bw = (tgt - b0_vec) * w

    n = A_subset.shape[1]
    lb = 0.0  # lower bound 
    ub = np.full(n, V_MAX, dtype=float) #upper bound

    res = lsq_linear(Aw, bw, bounds=(lb, ub), lsmr_tol="auto", verbose=0)
    return res.x


def optimize_single_sensor(sensor_id: int, target: np.ndarray) -> dict:
    # Empty-room field at this sensor
    b0 = load_empty_room_sensor_field(EMPTY_ROOM_PATH, sensor_id)  # (3,)

    # Build A for this sensor (3, ncoils)
    A_cols = []
    coil_labels = []
    for coil in COILS:
        stats_csv = TUNING_DIR / TUNING_STATS_FILENAME.format(coil=coil)
        if not stats_csv.exists():
            raise FileNotFoundError(
                f"Could not find tuning curve stats CSV for coil '{coil}'. Expected: {stats_csv}"
            )
        slopes = load_coil_slopes_for_sensor(stats_csv, sensor_id)
        A_cols.append(slopes)
        coil_labels.append(coil)

    A_all = np.stack(A_cols, axis=1)  # (3, ncoils)

    # selects until within tolernace
    used_idx: list[int] = []
    remaining_idx = list(range(A_all.shape[1]))

    best_v_used = np.zeros((0,), dtype=float)
    residual_now = b0.copy()

    max_to_use = len(COILS) if MAX_COILS_TO_USE is None else int(MAX_COILS_TO_USE)

    step = 0
    while (not within_tol(residual_now, target, TOL_NT)) and (len(used_idx) < max_to_use) and remaining_idx:
        step += 1

        best_candidate = None
        best_candidate_v = None
        best_candidate_residual = None
        best_candidate_score = None

        for cand in remaining_idx:
            trial_idx = used_idx + [cand]
            A_subset = A_all[:, trial_idx]
            v_trial = solve_subset(A_subset, b0, target)
            residual_trial = (A_subset @ v_trial) + b0
            s = score_error(residual_trial, target)

            if best_candidate_score is None or s < best_candidate_score:
                best_candidate = cand
                best_candidate_v = v_trial
                best_candidate_residual = residual_trial
                best_candidate_score = s

        if best_candidate is None:
            break

        used_idx.append(best_candidate)
        remaining_idx.remove(best_candidate)
        best_v_used = best_candidate_v
        residual_now = best_candidate_residual

    # Expand to full vector 
    V_all = np.zeros(len(COILS), dtype=float)
    for k, idx in enumerate(used_idx):
        V_all[idx] = float(best_v_used[k])

    final_residual = (A_all @ V_all) + b0
    final_err = final_residual - target
    success = within_tol(final_residual, target, TOL_NT)

    return {
        "sensor_id": int(sensor_id),
        "b0_Bx": float(b0[0]),
        "b0_By": float(b0[1]),
        "b0_Bz": float(b0[2]),
        "target_Bx": float(target[0]),
        "target_By": float(target[1]),
        "target_Bz": float(target[2]),
        "final_Bx": float(final_residual[0]),
        "final_By": float(final_residual[1]),
        "final_Bz": float(final_residual[2]),
        "err_Bx": float(final_err[0]),
        "err_By": float(final_err[1]),
        "err_Bz": float(final_err[2]),
        "success": bool(success),
        "n_coils_used": int(len(used_idx)),
        "coils_used": ";".join([COILS[i] for i in used_idx]),
        "V_all": V_all,
        "coil_labels": coil_labels,
    }


# run all sensor configs

target = np.array([TARGET_BX, TARGET_BY, TARGET_BZ], dtype=float)

print(" MULTI-SENSOR OPTIMIZATION ")
print(f"Sensors: {SENSOR_IDS}")
print(f"Target (nT): Bx={target[0]:.3f}, By={target[1]:.3f}, Bz={target[2]:.3f}")
print(f"Tolerance (nT): {TOL_NT:.3f} (all components)")
print(f"Bounds: 0 .. {V_MAX:.2f} V")

summary_rows = []

for sid in SENSOR_IDS:
    print(f"Optimizing sensor {sid}...")
    res = optimize_single_sensor(sid, target)

    # Save voltages for this sensor
    out_volt = pd.DataFrame({"coil": res["coil_labels"], "V": res["V_all"]})
    out_name_volt = f"optimized_voltages_sensor_{sid}_trial1.csv"
    out_csv_volt = COIL_CONFIG_DIR / out_name_volt
    out_volt.to_csv(out_csv_volt, index=False)

    # Save stats for this sensor
    out_stats = pd.DataFrame([
        {
            "sensor_id": res["sensor_id"],
            "b0_Bx": res["b0_Bx"],
            "b0_By": res["b0_By"],
            "b0_Bz": res["b0_Bz"],
            "target_Bx": res["target_Bx"],
            "target_By": res["target_By"],
            "target_Bz": res["target_Bz"],
            "final_Bx": res["final_Bx"],
            "final_By": res["final_By"],
            "final_Bz": res["final_Bz"],
            "err_Bx": res["err_Bx"],
            "err_By": res["err_By"],
            "err_Bz": res["err_Bz"],
            "success": res["success"],
            "n_coils_used": res["n_coils_used"],
            "coils_used": res["coils_used"],
        }
    ])

    out_name_stats = f"optimizer_stats_sensor{sid}.csv"
    out_csv_stats = COIL_CONFIG_DIR / out_name_stats
    out_stats.to_csv(out_csv_stats, index=False)

    summary_rows.append(out_stats.iloc[0].to_dict())

    print(
        f"  -> success={res['success']} | coils_used={res['n_coils_used']} | "
        f"final (nT) Bx={res['final_Bx']:.3f}, By={res['final_By']:.3f}, Bz={res['final_Bz']:.3f}"
    )

# Total sensor summary
out_summary = pd.DataFrame(summary_rows)
out_csv_summary = COIL_CONFIG_DIR / "trial1_sensors.csv"
out_summary.to_csv(out_csv_summary, index=False)

print("Saved per-sensor voltages as: optimized_voltages_sensorX.csv")
print("Saved per-sensor stats as: optimizer_stats_sensorX.csv")
print("Saved combined summary:", out_csv_summary)
