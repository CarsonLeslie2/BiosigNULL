# VSET_LIST: Initial voltages per coil
# GUI: single STOP button only
# STOP sets all VSET to 0, ISET to 0, turns all outputs OFF, closes ports, exits script
# VSCode: pip install pyserial tkinter pandas openpyxl

import time
import serial
import tkinter as tk
from tkinter import filedialog

import pandas as pd

# ----------------------------
# CONFIG
# ----------------------------
BAUD = 9600
TERMINATOR = "\r\n"

SAFE_MAX_V = 15.0
INTERVAL_MS = 250  
VSET_TOL = 0.05
ISET_TOL = 0.05

# read in volts
READ_IN_VOLTAGES = True

# One PSU per coil (channel 1 commands). NEEDS TO BE WORKED FOR EACH COMPUTER. 
COILS = [
    {"name": "r1",  "port": "COM3",  "chan": 1},
    {"name": "r2", "port": "COM4", "chan": 1},
    {"name": "r3",  "port": "COM5",  "chan": 1},
    {"name": "r4", "port": "COM6", "chan": 1},
    {"name": "r5",  "port": "COM7",  "chan": 1},
    {"name": "r6",  "port": "COM8",  "chan": 1},
    {"name": "r7",  "port": "COM9",  "chan": 1},
    {"name": "r8",  "port": "COM10", "chan": 1},
    {"name": "r9",  "port": "COM11", "chan": 1},
    {"name": "r10", "port": "COM12", "chan": 1},
    {"name": "r11", "port": "COM13", "chan": 1},
    {"name": "r12",  "port": "COM21",  "chan": 1},
    {"name": "r13",  "port": "COM20",  "chan": 1},
    {"name": "r14",  "port": "COM19",  "chan": 1},
    {"name": "r15",  "port": "COM18",  "chan": 1},
    {"name": "r16",  "port": "COM17",  "chan": 1},
    {"name": "c1",  "port": "COM16", "chan": 1},
    {"name": "c2",  "port": "COM15", "chan": 1},
    {"name": "c3", "port": "COM14", "chan": 1},
]

# Initial setpoints, currently by hand :(
VSET_LIST = {
    "r1": 9.074,
    "r2": 0,
    "r3": 0,
    "r4": 15,
    "r5": 0,
    "r6": 0,
    "r7": 8.935,
    "r8": 15,
    "r9": 15,
    "r10": 15,
    "r11": 1.577,
    "r12": 0,
    "r13": 0,
    "r14": 0,
    "r15": 0,
    "r16": 15,
    "c1": 0,
    "c2": 0.547,
    "c3": 2.795,
}

# overwrites the list if toggled.
if READ_IN_VOLTAGES:
    _picker = tk.Tk()
    _picker.withdraw()
    _picker.update()
    excel_path = filedialog.askopenfilename(
        title="Select CSV/Excel file with initial voltages",
        filetypes=[
            ("Voltage sheets", "*.csv *.xlsx *.xls"),
            ("CSV files", "*.csv"),
            ("Excel files", "*.xlsx *.xls"),
            ("All files", "*.*"),
        ],
    )
    try:
        _picker.destroy()
    except Exception:
        pass

    if not excel_path:
        raise RuntimeError("READ_IN_VOLTAGES=True but no Excel file was selected.")

    # Read CSV or Excel
    p_lower = excel_path.lower()
    if p_lower.endswith(".csv"):
        df_v = pd.read_csv(excel_path)
    else:
        # Let pandas choose; explicitly use openpyxl for .xlsx if available
        if p_lower.endswith(".xlsx"):
            df_v = pd.read_excel(excel_path, engine="openpyxl")
        else:
            df_v = pd.read_excel(excel_path)

    # normalize column names
    cols = {str(c).strip().lower(): c for c in df_v.columns}
    if "coil" not in cols or "v" not in cols:
        raise ValueError(
            f"Sheet must contain columns 'coil' and 'V' (found: {list(df_v.columns)})."
        )

    coil_col = cols["coil"]
    v_col = cols["v"]

    loaded = {}
    for _, row in df_v.iterrows():
        coil = str(row[coil_col]).strip()
        if not coil:
            continue
        try:
            v = float(row[v_col])
        except Exception:
            continue

        # Round to 2 decimals; values with |V| < 0.004 -> 0.00
        if abs(v) < 0.004:
            v = 0.0
        else:
            v = round(v, 2)

        loaded[coil] = v

    # Update VSET_LIST with any values present in the sheet
    for c in COILS:
        nm = c["name"]
        if nm in loaded:
            VSET_LIST[nm] = loaded[nm]


ISET_DEFAULT = 0.05  # A
ISET_LIST = {c["name"]: ISET_DEFAULT for c in COILS}

# base safety
for c in COILS:
    name = c["name"]
    v0 = float(VSET_LIST.get(name, 0.0))
    i0 = float(ISET_LIST.get(name, 0.0))

    if abs(v0) > SAFE_MAX_V:
        raise ValueError(f"{name}: |VSET| must be <= SAFE_MAX_V ({SAFE_MAX_V} V).")
    if i0 <= 0:
        raise ValueError(f"{name}: ISET must be > 0 A.")

# connect to PSU
psus = {}  # name -> serial.Serial
try:
    for c in COILS:
        name = c["name"]
        port = c["port"]
        psu = serial.Serial(port, BAUD, timeout=0.5)
        psus[name] = psu
        time.sleep(0.2)
except Exception:
    for psu in psus.values():
        try:
            psu.close()
        except:
            pass
    raise

# Start
for c in COILS:
    psu = psus[c["name"]]
    psu.write(("OUT0" + TERMINATOR).encode("ascii"))
    psu.flush()

# -set iv
vset_rb = {}
iset_rb = {}

for c in COILS:
    name = c["name"]
    ch = int(c["chan"])
    psu = psus[name]

    v0 = float(VSET_LIST.get(name, 0.0))
    i0 = float(ISET_LIST.get(name, 0.0))

    psu.write((f"ISET{ch}:{i0:.3f}" + TERMINATOR).encode("ascii")); psu.flush()
    psu.write((f"VSET{ch}:{v0:.2f}" + TERMINATOR).encode("ascii")); psu.flush()

    psu.reset_input_buffer()
    psu.write((f"VSET{ch}?" + TERMINATOR).encode("ascii")); psu.flush()
    time.sleep(0.1)
    v_rb_s = psu.read(200).decode(errors="ignore").strip()

    psu.reset_input_buffer()
    psu.write((f"ISET{ch}?" + TERMINATOR).encode("ascii")); psu.flush()
    time.sleep(0.1)
    i_rb_s = psu.read(200).decode(errors="ignore").strip()

    try:
        v_rb = float(v_rb_s)
    except:
        v_rb = None
    try:
        i_rb = float(i_rb_s)
    except:
        i_rb = None

    if v_rb is None or abs(v_rb - v0) > VSET_TOL:
        psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()
        print(f"closed coil {name}")
        for p in psus.values():
            try:
                p.close()
            except:
                pass
        raise RuntimeError(f"{name}: VSET readback mismatch (wanted {v0:.2f}, got {v_rb}). Output left OFF.")

    if i_rb is None or abs(i_rb - i0) > ISET_TOL:
        psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()
        print(f"closed coil {name}")
        for p in psus.values():
            try:
                p.close()
            except:
                pass
        raise RuntimeError(f"{name}: ISET readback mismatch (wanted {i0:.3f}, got {i_rb}). Output left OFF.")

    vset_rb[name] = v_rb
    iset_rb[name] = i_rb


def _kill_all_and_exit():
    # Replicate the requested kill logic for each PSU/COM
    for c in COILS:
        name = c["name"]
        ch = int(c["chan"])
        psu = psus.get(name)
        if psu is None:
            continue
        try:
            psu.write((f"VSET{ch}:0.00" + TERMINATOR).encode("ascii")); psu.flush()
            psu.write((f"ISET{ch}:0.000" + TERMINATOR).encode("ascii")); psu.flush()
            psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()
            print(f"closed coil {name}")
            time.sleep(0.2)
        except:
            pass
        try:
            psu.close()
        except:
            pass
    raise SystemExit(0)


# Before turning outputs ON, print initial voltages and ask user to confirm
print("\nInitial voltages to apply (VSET):")
print("-------------------------------")
print(f"{'coil':<6} {'VSET (V)':>12} {'port':>8}")
for c in COILS:
    nm = c["name"]
    v0 = float(VSET_LIST.get(nm, 0.0))
    print(f"{nm:<6} {v0:>12.4f} {c['port']:>8}")
print("-------------------------------")
resp = input("Proceed to turn outputs ON? [y/N]: ").strip().lower()
if resp not in ("y", "yes"):
    _kill_all_and_exit()


for c in COILS:
    psu = psus[c["name"]]
    psu.write(("OUT1" + TERMINATOR).encode("ascii"))
    psu.flush()

# STOP-only GUI
root = tk.Tk()
root.title("KORAD KD STOP")
root.geometry("260x120")

running = True

def shutdown_everything():
    global running
    running = False

    # Replicate the requested kill logic for each PSU/COM
    for c in COILS:
        name = c["name"]
        ch = int(c["chan"])
        psu = psus.get(name)
        if psu is None:
            continue
        try:
            psu.write((f"VSET{ch}:0.00" + TERMINATOR).encode("ascii")); psu.flush()
            psu.write((f"ISET{ch}:0.000" + TERMINATOR).encode("ascii")); psu.flush()
            psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()
            print(f"closed coil {name}")
        except:
            pass

        try:
            psu.close()
        except:
            pass

    root.destroy()

def stop_button():
    shutdown_everything()

def on_close():
    shutdown_everything()

btn = tk.Button(
    root,
    text="STOP",
    font=("Segoe UI", 20, "bold"),
    command=stop_button,
    height=2,
    width=10,
)
btn.pack(expand=True)

root.protocol("WM_DELETE_WINDOW", on_close)

root.mainloop()
