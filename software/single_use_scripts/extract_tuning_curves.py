import re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

COIL = "c3"
RAW_TUNING_DATE_TAG = "2026_02_20"
OUT_DATE_TAG = "2026_02_20"
tag_name = f"{COIL} tuning curves"

SCRIPT_DIR = Path(__file__).resolve().parent


BASE_DIR = None
for p in [SCRIPT_DIR, *SCRIPT_DIR.parents]:
    name = p.name.lower()
    if name == "biosignull" or name.startswith("biosignull_"):
        BASE_DIR = p
        break


if BASE_DIR is None:
    raise RuntimeError(f"Could not locate BiosigNULL Script dir is: {SCRIPT_DIR}")

data_dir = BASE_DIR / "raw_data" / RAW_TUNING_DATE_TAG
out_dir = BASE_DIR / "tuning" / OUT_DATE_TAG
out_dir.mkdir(parents=True, exist_ok=True)

paths = sorted(data_dir.glob(f"{COIL}_*v_raw.txt"))
if not paths:
    raise FileNotFoundError(f"No files found matching {COIL}_*v_raw.txt in {data_dir}")

rows = []
for p in paths:
    m = re.search(rf"{re.escape(COIL)}_([0-9]*\.?[0-9]+)v_raw\.txt$", p.name, flags=re.IGNORECASE)
    if not m:
        continue
    V = float(m.group(1))

    df = pd.read_csv(
        p,
        header=None,
        names=["sensor", "tag", "Bx", "By", "Bz"],
        engine="python",
        skip_blank_lines=True,
        na_values=["---", "--", "-"],
    )

    df["sensor"] = df["sensor"].astype(str).str.strip()
    df = df[df["sensor"].str.contains(":")]
    df["sensor_id"] = pd.to_numeric(df["sensor"].str.split(":").str[-1], errors="coerce")

    df = df[(df["sensor_id"] >= 1) & (df["sensor_id"] <= 13)]
    df["V"] = V

    for comp in ["Bx", "By", "Bz"]:
        df[comp] = pd.to_numeric(df[comp], errors="coerce")

    df = df.dropna(subset=["sensor_id", "Bx", "By", "Bz"])
    rows.append(df[["sensor_id", "tag", "V", "Bx", "By", "Bz"]])

data = pd.concat(rows, ignore_index=True)
if data.empty:
    raise RuntimeError("Parsed data is empty (check file format / missing values).")

stats = []
fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharex=True)
comps = [("Bx", axes[0]), ("By", axes[1]), ("Bz", axes[2])]

for comp, ax in comps:
    ax.set_title(f"{COIL} {comp} vs V")
    ax.set_xlabel("V (V)")
    ax.set_ylabel(comp)

legend_handles = []
legend_labels = []

for sid in range(1, 14):
    d = data[data["sensor_id"] == sid].sort_values("V")
    x = d["V"].to_numpy(dtype=float)
    if x.size < 2:
        continue

    for comp, ax in comps:
        y = d[comp].to_numpy(dtype=float)
        if y.size < 2:
            continue

        a, b = np.polyfit(x, y, 1)
        yhat = a * x + b
        ss_res = np.sum((y - yhat) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = np.nan if ss_tot == 0 else 1 - ss_res / ss_tot
        rmse = float(np.sqrt(np.mean((y - yhat) ** 2)))

        stats.append(
            {
                "sensor_id": int(sid),
                "component": comp,
                "slope_per_V": float(a),
                "intercept": float(b),
                "r2": float(r2) if r2 == r2 else np.nan,
                "rmse": rmse,
                "n_points": int(len(x)),
                "V_min": float(np.min(x)),
                "V_max": float(np.max(x)),
                "tag": str(d["tag"].iloc[0]) if "tag" in d.columns and len(d["tag"]) else "",
                "coil": COIL,
            }
        )

        pts = ax.plot(x, y, marker="o", linestyle="", label=f"S{sid}")
        line = ax.plot(x, yhat, linestyle="-", linewidth=1)

        if comp == "Bx":
            legend_handles.append(line[0])
            legend_labels.append(f"S{sid}")

for _, ax in comps:
    ax.grid(True, alpha=0.3)

fig.legend(
    legend_handles,
    legend_labels,
    loc="center left",
    bbox_to_anchor=(1.01, 0.5),
    title="Sensors",
    frameon=True,
)

fig.tight_layout(rect=[0, 0, 0.86, 1])

plot_path = out_dir / f"{tag_name}_plot.png"
csv_path = out_dir / f"{tag_name}_stats.csv"

fig.savefig(plot_path, dpi=200)
pd.DataFrame(stats).sort_values(["sensor_id", "component"]).to_csv(csv_path, index=False)

print("Saved plot:", plot_path)
print("Saved stats:", csv_path)
plt.show()
