import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear


# CONFIG 

TUNING_DATE_TAG = "2026_02_12"       # BiosigNULL/tuning/<tag>/
EMPTY_ROOM_DATE_TAG = "2026_02_24"  # BiosigNULL/raw_data/<tag>/empty_room.txt
COIL_CONFIG_DATE_TAG = "2026_02_24"  # BiosigNULL/coil_configs/<tag>/coil_voltages.csv

V_MAX = 15 #MAX VOLTAGE
W_BX, W_BY, W_BZ = 1, 1, 10  # WEIGHTS

COILS = ["r1", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15", "r16", "c2", "c3"]
TUNING_STATS_FILENAME = "{coil} tuning curves_stats.csv"


# finds pathing for BiosigNULL

SCRIPT_DIR = Path(__file__).resolve().parent

BASE_DIR = None
for p in [SCRIPT_DIR, *SCRIPT_DIR.parents]:
    name = p.name.lower()
    if name == "biosignull" or name.startswith("biosignull_"):
        BASE_DIR = p
        break

if BASE_DIR is None:
    raise RuntimeError(f"Error: Script dir is: {SCRIPT_DIR}")


# Ouptut pathing 

COIL_CONFIG_DIR = BASE_DIR / "coil_configs" / COIL_CONFIG_DATE_TAG
COIL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


TUNING_DIR = BASE_DIR / "tuning" / TUNING_DATE_TAG
EMPTY_ROOM_PATH = BASE_DIR / "raw_data" / EMPTY_ROOM_DATE_TAG / "trial1OFF.txt"


# load empty room field

sensor_ids = np.arange(1, 14, dtype=int)

empty = pd.read_csv(
    EMPTY_ROOM_PATH,
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

empty = empty.dropna(subset=["sensor_id", "Bx", "By", "Bz"]).sort_values("sensor_id")

bBx = np.array(
    [empty.loc[empty["sensor_id"] == sid, "Bx"].iloc[0] if (empty["sensor_id"] == sid).any() else 0.0
     for sid in sensor_ids],
    dtype=float,
)
bBy = np.array(
    [empty.loc[empty["sensor_id"] == sid, "By"].iloc[0] if (empty["sensor_id"] == sid).any() else 0.0
     for sid in sensor_ids],
    dtype=float,
)
bBz = np.array(
    [empty.loc[empty["sensor_id"] == sid, "Bz"].iloc[0] if (empty["sensor_id"] == sid).any() else 0.0
     for sid in sensor_ids],
    dtype=float,
)

b0 = np.concatenate([bBx, bBy, bBz], axis=0)  # (39,)


# load tuning curves

A_cols = []
coil_labels = []

for coil in COILS:
    stats_csv = TUNING_DIR / TUNING_STATS_FILENAME.format(coil=coil)

    if not stats_csv.exists():
        raise FileNotFoundError(
            f"Could not find tuning curve stats CSV for coil '{coil}'. Expected: {stats_csv}"
        )

    print(f"Loaded tuning slopes for {coil} from: {stats_csv}")

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

    df = df[df["sensor_id"].between(1, 13)]
    df = df[df["component"].isin(["Bx", "By", "Bz"])]

    piv = df.pivot_table(index="sensor_id", columns="component", values="slope_per_V", aggfunc="mean")
    piv = piv.reindex(sensor_ids)

    sBx = piv["Bx"].fillna(0.0).to_numpy(dtype=float) if "Bx" in piv.columns else np.zeros(13, dtype=float)
    sBy = piv["By"].fillna(0.0).to_numpy(dtype=float) if "By" in piv.columns else np.zeros(13, dtype=float)
    sBz = piv["Bz"].fillna(0.0).to_numpy(dtype=float) if "Bz" in piv.columns else np.zeros(13, dtype=float)

    A_cols.append(np.concatenate([sBx, sBy, sBz], axis=0))
    coil_labels.append(coil)

A = np.stack(A_cols, axis=1)  # (39, ncoils)

# Weighted LSQ + bounds

w = np.concatenate(
    [
        np.full(13, np.sqrt(W_BX), dtype=float),
        np.full(13, np.sqrt(W_BY), dtype=float),
        np.full(13, np.sqrt(W_BZ), dtype=float),
    ],
    axis=0,
)

Aw = A * w[:, None]
bw = (-b0) * w

res = lsq_linear(Aw, bw, bounds=(0, V_MAX), lsmr_tol="auto", verbose=0)
V_sol = res.x

print("\nCoils:", coil_labels)
print("Voltages (V):", V_sol)
print("Success:", res.success)

# Save outputs under BiosigNULL/coil_configs/datestring

residual = (A @ V_sol) + b0
Bx_res = residual[0:13]
By_res = residual[13:26]
Bz_res = residual[26:39]

out_resid = pd.DataFrame(
    {"sensor_id": sensor_ids, "Bx_residual": Bx_res, "By_residual": By_res, "Bz_residual": Bz_res}
)
out_volt = pd.DataFrame({"coil": coil_labels, "V": V_sol})

tag = f"tune-{TUNING_DATE_TAG}_empty-{EMPTY_ROOM_DATE_TAG}"

out_csv_resid = COIL_CONFIG_DIR / "optimizer_residuals.csv"
out_csv_volt  = COIL_CONFIG_DIR / "coil_voltages.csv"


out_resid.to_csv(out_csv_resid, index=False)
out_volt.to_csv(out_csv_volt, index=False)

print("\nSaved:", out_csv_resid)
print("Saved:", out_csv_volt)
