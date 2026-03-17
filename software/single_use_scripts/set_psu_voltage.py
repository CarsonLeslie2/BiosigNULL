# gui voltage for 1 psu
# VSET: Initial voltage
# GUI shows measured Vout/Iout every INTERVAL_MS
# GUI lets you type a NEW voltage and click "APPLY VOLTAGE"
# STOP sets VSET to 0, ISET to 0, turns output OFF, closes port, exits script

# VSCode: pip install pyserial, tkinter, time

import time
import serial
import tkinter as tk

# config
PORT = "COM16"
BAUD = 9600

SAFE_MAX_V = 15
VSET = 1.0
ISET = 0.05

INTERVAL_MS = 250
VSET_TOL = 0.05
ISET_TOL = 0.05


# safety check (initial)
if VSET < 0 or VSET > SAFE_MAX_V:
    raise ValueError(f"VSET must be between 0 and SAFE_MAX_V ({SAFE_MAX_V} V).")
if ISET <= 0:
    raise ValueError("ISET must be > 0 A.")

psu = serial.Serial(PORT, BAUD, timeout=0.5)
time.sleep(0.2)

TERMINATOR = "\r\n"   # if empty replies, try "\r"

def send(cmd: str):
    psu.write((cmd + TERMINATOR).encode("ascii"))
    psu.flush()

def query(cmd: str) -> str:
    psu.reset_input_buffer()
    send(cmd)
    time.sleep(0.1)
    return psu.read(200).decode(errors="ignore").strip()

def parse_float(s: str):
    try:
        return float(s)
    except:
        return None

# ---- start safe ----
send("OUT0")

# ---- set initial I/V ----
send(f"ISET1:{ISET:.3f}")
send(f"VSET1:{VSET:.2f}")

# ---- confirm initial setpoints ----
vset_rb = parse_float(query("VSET1?"))
iset_rb = parse_float(query("ISET1?"))

if vset_rb is None or abs(vset_rb - VSET) > VSET_TOL:
    send("OUT0")
    psu.close()
    raise RuntimeError(f"VSET readback mismatch (wanted {VSET:.2f}, got {vset_rb}). Output left OFF.")

if iset_rb is None or abs(iset_rb - ISET) > ISET_TOL:
    send("OUT0")
    psu.close()
    raise RuntimeError(f"ISET readback mismatch (wanted {ISET:.3f}, got {iset_rb}). Output left OFF.")

send("OUT1")

# ---------------- GUI ----------------
root = tk.Tk()
root.title("KORAD KD Live Control")
root.geometry("520x320")

status = tk.StringVar(value=f"RUNNING  (Max Amps ={ISET:.3f} A, Max Volts ={SAFE_MAX_V:.2f} V)")
readout = tk.StringVar(value="Vout: -- V    Iout: -- A")

vset_var = tk.StringVar(value=f"{VSET:.2f}")     # entry field
vset_now = tk.StringVar(value=f"VSET (device): {vset_rb:.2f} V")

running = True

def shutdown_everything():
    global running
    running = False
    send("OUT0")
    send("VSET1:0.00")
    send("ISET1:0.000")
    psu.close()
    root.destroy()


def stop_button():
    status.set("STOPPED")
    shutdown_everything()

def on_close():
    shutdown_everything()

def apply_voltage():
    # simple live voltage adjustment with safety + readback confirm
    global VSET
    new_v = parse_float(vset_var.get())

    if new_v is None:
        status.set("Bad voltage input (not a number)")
        return

    if new_v < 0 or new_v > SAFE_MAX_V:
        status.set(f"Rejected: {new_v:.2f} V outside 0..{SAFE_MAX_V:.2f} V")
        return

    send(f"VSET1:{new_v:.2f}")
    rb = parse_float(query("VSET1?"))

    if rb is None or abs(rb - new_v) > VSET_TOL:
        status.set(f"Apply failed (wanted {new_v:.2f}, got {rb})")
        return

    VSET = new_v
    vset_now.set(f"VSET (device): {rb:.2f} V")
    status.set(f"Applied VSET={rb:.2f} V")

def update_readout():
    if not running:
        return
    v = query("VOUT1?")
    i = query("IOUT1?")
    readout.set(f"Vout: {v} V    Iout: {i} A")
    root.after(INTERVAL_MS, update_readout)

tk.Label(root, textvariable=status, font=("Segoe UI", 12)).pack(pady=10)
tk.Label(root, textvariable=readout, font=("Consolas", 14)).pack(pady=10)
tk.Label(root, textvariable=vset_now, font=("Segoe UI", 11)).pack(pady=5)

# voltage control row
row = tk.Frame(root)
row.pack(pady=8)

tk.Label(row, text="New Voltage (V):", font=("Segoe UI", 11)).pack(side="left", padx=6)
tk.Entry(row, textvariable=vset_var, width=10, font=("Segoe UI", 11)).pack(side="left", padx=6)

tk.Button(
    row,
    text="APPLY VOLTAGE",
    font=("Segoe UI", 11),
    command=apply_voltage,
    height=1,
    width=14
).pack(side="left", padx=6)

# STOP
tk.Button(
    root,
    text="STOP",
    font=("Segoe UI", 16),
    command=stop_button,
    height=2,
    width=22
).pack(pady=14)

root.protocol("WM_DELETE_WINDOW", on_close)

update_readout()
root.mainloop()
