
# VSET_LIST: Initial voltages per coil
# GUI shows measured Vout/Iout every INTERVAL_MS for each coil
# GUI lets you type NEW voltages (one per coil) and click "APPLY VOLTAGES"
# STOP sets all VSET to 0, ISET to 0, turns all outputs OFF, closes ports, exits script
# gui is VERY LAGGY WITH 19 COILS. Not sure if software or if my computer is bad. 
# VSCode: pip install pyserial tkinter

import time
import serial
import tkinter as tk

# config
BAUD = 9600
TERMINATOR = "\r\n"   

SAFE_MAX_V = 15.0
INTERVAL_MS = 250
VSET_TOL = 0.05
ISET_TOL = 0.05

# One PSU per coil (channel 1 commands). NEEDS TO BE WORKED FOR EACH COMPUTER
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


ISET_DEFAULT = 0.05  # A
ISET_LIST = {c["name"]: ISET_DEFAULT for c in COILS}

# base safety 

for c in COILS:
    name = c["name"]
    v0 = float(VSET_LIST.get(name, 0.0))
    i0 = float(ISET_LIST.get(name, 0.0))

    if v0 < 0 or v0 > SAFE_MAX_V:
        raise ValueError(f"{name}: VSET must be between 0 and SAFE_MAX_V ({SAFE_MAX_V} V).")
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
        for p in psus.values():
            try:
                p.close()
            except:
                pass
        raise RuntimeError(f"{name}: VSET readback mismatch (wanted {v0:.2f}, got {v_rb}). Output left OFF.")

    if i_rb is None or abs(i_rb - i0) > ISET_TOL:
        psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()
        for p in psus.values():
            try:
                p.close()
            except:
                pass
        raise RuntimeError(f"{name}: ISET readback mismatch (wanted {i0:.3f}, got {i_rb}). Output left OFF.")

    vset_rb[name] = v_rb
    iset_rb[name] = i_rb

for c in COILS:
    psu = psus[c["name"]]
    psu.write(("OUT1" + TERMINATOR).encode("ascii"))
    psu.flush()

# Gooey
root = tk.Tk()
root.title("KORAD KD Live Control (Multi-Coil)")
root.geometry("860x520")

status = tk.StringVar(value=f"RUNNING  (Max Volts ={SAFE_MAX_V:.2f} V)")
running = True

vset_var = {}
vset_now = {}
readout = {}

for c in COILS:
    name = c["name"]
    v0 = float(VSET_LIST.get(name, 0.0))
    vset_var[name] = tk.StringVar(value=f"{v0:.6g}")  # keeps tiny numbers readable
    vset_now[name] = tk.StringVar(value=f"VSET (device): {vset_rb.get(name, 0.0):.2f} V")
    readout[name] = tk.StringVar(value="Vout: -- V    Iout: -- A")

def shutdown_everything():
    global running
    running = False

    for c in COILS:
        name = c["name"]
        ch = int(c["chan"])
        psu = psus[name]
        try:
            psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()
            psu.write((f"VSET{ch}:0.00" + TERMINATOR).encode("ascii")); psu.flush()
            psu.write((f"ISET{ch}:0.000" + TERMINATOR).encode("ascii")); psu.flush()
        except:
            pass

    for psu in psus.values():
        try:
            psu.close()
        except:
            pass

    root.destroy()

def stop_button():
    status.set("STOPPED")
    shutdown_everything()

def on_close():
    shutdown_everything()

def apply_voltages():
    any_fail = False
    msgs = []

    for c in COILS:
        name = c["name"]
        ch = int(c["chan"])
        psu = psus[name]

        try:
            new_v = float(vset_var[name].get())
        except:
            any_fail = True
            msgs.append(f"{name}: bad input")
            continue

        if new_v < 0 or new_v > SAFE_MAX_V:
            any_fail = True
            msgs.append(f"{name}: rejected {new_v:.2f}V")
            continue

        psu.write((f"VSET{ch}:{new_v:.2f}" + TERMINATOR).encode("ascii")); psu.flush()

        psu.reset_input_buffer()
        psu.write((f"VSET{ch}?" + TERMINATOR).encode("ascii")); psu.flush()
        time.sleep(0.1)
        rb_s = psu.read(200).decode(errors="ignore").strip()

        try:
            rb = float(rb_s)
        except:
            rb = None

        if rb is None or abs(rb - new_v) > VSET_TOL:
            any_fail = True
            msgs.append(f"{name}: apply failed ({rb})")
            continue

        vset_now[name].set(f"VSET (device): {rb:.2f} V")

    status.set(" | ".join(msgs) if any_fail else "Applied all voltages OK")

def update_readout():
    if not running:
        return

    for c in COILS:
        name = c["name"]
        ch = int(c["chan"])
        psu = psus[name]

        psu.reset_input_buffer()
        psu.write((f"VOUT{ch}?" + TERMINATOR).encode("ascii")); psu.flush()
        time.sleep(0.05)
        v = psu.read(200).decode(errors="ignore").strip()

        psu.reset_input_buffer()
        psu.write((f"IOUT{ch}?" + TERMINATOR).encode("ascii")); psu.flush()
        time.sleep(0.05)
        i = psu.read(200).decode(errors="ignore").strip()

        readout[name].set(f"Vout: {v} V    Iout: {i} A")

    root.after(INTERVAL_MS, update_readout)

tk.Label(root, textvariable=status, font=("Segoe UI", 12)).pack(pady=10)

table = tk.Frame(root)
table.pack(pady=8, padx=10, fill="x")

tk.Label(table, text="Coil", font=("Segoe UI", 11, "bold"), width=10, anchor="w").grid(row=0, column=0, padx=6, pady=4)
tk.Label(table, text="Readout", font=("Segoe UI", 11, "bold"), width=28, anchor="w").grid(row=0, column=1, padx=6, pady=4)
tk.Label(table, text="VSET (device)", font=("Segoe UI", 11, "bold"), width=18, anchor="w").grid(row=0, column=2, padx=6, pady=4)
tk.Label(table, text="New Voltage (V)", font=("Segoe UI", 11, "bold"), width=16, anchor="w").grid(row=0, column=3, padx=6, pady=4)

for r, c in enumerate(COILS, start=1):
    name = c["name"]
    tk.Label(table, text=name, font=("Segoe UI", 11), width=10, anchor="w").grid(row=r, column=0, padx=6, pady=4)
    tk.Label(table, textvariable=readout[name], font=("Consolas", 12), width=28, anchor="w").grid(row=r, column=1, padx=6, pady=4)
    tk.Label(table, textvariable=vset_now[name], font=("Segoe UI", 11), width=18, anchor="w").grid(row=r, column=2, padx=6, pady=4)
    tk.Entry(table, textvariable=vset_var[name], width=12, font=("Segoe UI", 11)).grid(row=r, column=3, padx=6, pady=4, sticky="w")

btn_row = tk.Frame(root)
btn_row.pack(pady=10)

tk.Button(
    btn_row,
    text="APPLY VOLTAGES",
    font=("Segoe UI", 12),
    command=apply_voltages,
    height=1,
    width=18
).pack(side="left", padx=10)

tk.Button(
    btn_row,
    text="STOP",
    font=("Segoe UI", 16),
    command=stop_button,
    height=2,
    width=18
).pack(side="left", padx=10)

root.protocol("WM_DELETE_WINDOW", on_close)

update_readout()
root.mainloop()
