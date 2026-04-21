# carson_pc_controller.py

import json
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import pandas as pd
import pyfirmata
import serial


BAUD = 9600
TERMINATOR = "\r\n"

SAFE_MAX_V = 15.0
VSET_TOL = 0.05
ISET_TOL = 0.05

########################
# these are what can be changed.
CONFIG_NAME = "Carson_PC"
ARDUINO_PORT = "COM22"
READ_IN_VOLTAGES = False
########################

PULSE_MS = 50
PULSE_GAP_S = 1.0

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / f"{CONFIG_NAME}.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as file:
    config = json.load(file)

COILS = config["coils"]
ARDUINO_PINS = config["arduino_pins"]

VSET_LIST = {
    "r1": -1,
    "r2": -1,
    "r3": -1,
    "r4": 0,
    "r5": 0,
    "r6": 0,
    "r7": 0,
    "r8": 0,
    "r9": 0,
    "r10": 0,
    "r11": 0,
    "r12": 0,
    "r13": 0,
    "r14": 0,
    "r15": 0,
    "r16": 0,
    "c1": 0,
    "c2": 0,
    "c3": 0,
}

if READ_IN_VOLTAGES:
    picker = tk.Tk()
    picker.withdraw()
    picker.update()
    voltage_path = filedialog.askopenfilename(
        title="Select CSV/Excel file with initial voltages",
        filetypes=[
            ("Voltage sheets", "*.csv *.xlsx *.xls"),
            ("CSV files", "*.csv"),
            ("Excel files", "*.xlsx *.xls"),
            ("All files", "*.*"),
        ],
    )
    picker.destroy()

    if voltage_path.lower().endswith(".csv"):
        df_v = pd.read_csv(voltage_path)
    elif voltage_path.lower().endswith(".xlsx"):
        df_v = pd.read_excel(voltage_path, engine="openpyxl")
    else:
        df_v = pd.read_excel(voltage_path)

    cols = {str(c).strip().lower(): c for c in df_v.columns}
    coil_col = cols["coil"]
    v_col = cols["v"]

    loaded = {}
    for _, row in df_v.iterrows():
        coil = str(row[coil_col]).strip()
        if coil:
            voltage = float(row[v_col])
            loaded[coil] = 0.0 if abs(voltage) < 0.004 else round(voltage, 2)

    for c in COILS:
        name = c["name"]
        if name in loaded:
            VSET_LIST[name] = loaded[name]

ISET_DEFAULT = 0.05
ISET_LIST = {c["name"]: ISET_DEFAULT for c in COILS}


def get_pin(coil_name, action):
    for item in ARDUINO_PINS:
        if item["coil"] == coil_name and item["action"] == action:
            return int(item["pin"])


def pulse_pin(board, pin):
    board.digital[pin].mode = pyfirmata.OUTPUT
    board.digital[pin].write(1)
    time.sleep(PULSE_MS / 1000)
    board.digital[pin].write(0)
    time.sleep(PULSE_GAP_S)


def pulse_relay(board, coil_name, action):
    pin = get_pin(coil_name, action)
    print(f"Sending {action} pulse to {coil_name} on Arduino pin {pin}")
    pulse_pin(board, pin)
    print(f"Finished {action} pulse to {coil_name}")


board = pyfirmata.Arduino(ARDUINO_PORT)

for c in COILS:
    pulse_relay(board, c["name"], "reset")

for name, voltage in VSET_LIST.items():
    if float(voltage) < 0:
        pulse_relay(board, name, "set")
        VSET_LIST[name] = abs(float(voltage))

board.exit()

for c in COILS:
    name = c["name"]
    v0 = float(VSET_LIST.get(name, 0.0))
    i0 = float(ISET_LIST.get(name, 0.0))

    if abs(v0) > SAFE_MAX_V:
        raise ValueError(f"{name}: |VSET| must be <= SAFE_MAX_V ({SAFE_MAX_V} V).")
    if i0 <= 0:
        raise ValueError(f"{name}: ISET must be > 0 A.")

psus = {}

for c in COILS:
    name = c["name"]
    port = c["port"]
    psus[name] = serial.Serial(port, BAUD, timeout=0.5)
    time.sleep(0.2)

for c in COILS:
    psu = psus[c["name"]]
    psu.write(("OUT0" + TERMINATOR).encode("ascii"))
    psu.flush()

vset_rb = {}
iset_rb = {}

for c in COILS:
    name = c["name"]
    ch = int(c["chan"])
    psu = psus[name]

    v0 = float(VSET_LIST.get(name, 0.0))
    i0 = float(ISET_LIST.get(name, 0.0))

    psu.write((f"ISET{ch}:{i0:.3f}" + TERMINATOR).encode("ascii"))
    psu.flush()
    psu.write((f"VSET{ch}:{v0:.2f}" + TERMINATOR).encode("ascii"))
    psu.flush()

    psu.reset_input_buffer()
    psu.write((f"VSET{ch}?" + TERMINATOR).encode("ascii"))
    psu.flush()
    time.sleep(0.1)
    v_rb = float(psu.read(200).decode(errors="ignore").strip())

    psu.reset_input_buffer()
    psu.write((f"ISET{ch}?" + TERMINATOR).encode("ascii"))
    psu.flush()
    time.sleep(0.1)
    i_rb = float(psu.read(200).decode(errors="ignore").strip())

    if abs(v_rb - v0) > VSET_TOL:
        psu.write(("OUT0" + TERMINATOR).encode("ascii"))
        psu.flush()
        raise RuntimeError(f"{name}: VSET readback mismatch.")

    if abs(i_rb - i0) > ISET_TOL:
        psu.write(("OUT0" + TERMINATOR).encode("ascii"))
        psu.flush()
        raise RuntimeError(f"{name}: ISET readback mismatch.")

    vset_rb[name] = v_rb
    iset_rb[name] = i_rb


def kill_all_and_exit():
    for c in COILS:
        name = c["name"]
        ch = int(c["chan"])
        psu = psus.get(name)

        if psu is not None:
            psu.write((f"VSET{ch}:0.00" + TERMINATOR).encode("ascii"))
            psu.flush()
            psu.write((f"ISET{ch}:0.000" + TERMINATOR).encode("ascii"))
            psu.flush()
            psu.write(("OUT0" + TERMINATOR).encode("ascii"))
            psu.flush()
            print(f"closed coil {name}")
            time.sleep(0.2)
            psu.close()

    raise SystemExit(0)


print("\nInitial voltages to apply (VSET):")
print("-------------------------------")
print(f"{'coil':<6} {'VSET (V)':>12} {'port':>8}")

for c in COILS:
    name = c["name"]
    v0 = float(VSET_LIST.get(name, 0.0))
    print(f"{name:<6} {v0:>12.4f} {c['port']:>8}")

print("-------------------------------")
resp = input("Proceed to turn outputs ON? [y/N]: ").strip().lower()

if resp not in ("y", "yes"):
    kill_all_and_exit()

for c in COILS:
    psu = psus[c["name"]]
    psu.write(("OUT1" + TERMINATOR).encode("ascii"))
    psu.flush()

root = tk.Tk()
root.title("KORAD KD STOP")
root.geometry("260x120")

running = True


def shutdown_everything():
    global running
    running = False

    for c in COILS:
        name = c["name"]
        ch = int(c["chan"])
        psu = psus.get(name)

        if psu is not None:
            psu.write((f"VSET{ch}:0.00" + TERMINATOR).encode("ascii"))
            psu.flush()
            psu.write((f"ISET{ch}:0.000" + TERMINATOR).encode("ascii"))
            psu.flush()
            psu.write(("OUT0" + TERMINATOR).encode("ascii"))
            psu.flush()
            print(f"closed coil {name}")
            psu.close()

    root.destroy()


btn = tk.Button(
    root,
    text="STOP",
    font=("Segoe UI", 20, "bold"),
    command=shutdown_everything,
    height=2,
    width=10,
)
btn.pack(expand=True)

root.protocol("WM_DELETE_WINDOW", shutdown_everything)

root.mainloop()