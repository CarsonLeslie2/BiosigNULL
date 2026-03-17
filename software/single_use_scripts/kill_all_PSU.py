
"Killing PSUs."
"Running this will turn of all PSUs"

import time
import serial

BAUD = 9600
TERMINATOR = "\r\n"   
TIMEOUT = 0.2

for n in range(3, 22): # adjust as needed. These are COM values, iterate over the entire list. (Default is 3-22)
    port = f"COM{n}"
    try:
        psu = serial.Serial(port, BAUD, timeout=TIMEOUT, write_timeout=TIMEOUT)
        time.sleep(0.1)

        psu.write(("VSET1:0.00" + TERMINATOR).encode("ascii")); psu.flush()
        psu.write(("ISET1:0.000" + TERMINATOR).encode("ascii")); psu.flush()
        psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()

        psu.close()
        print("KILLED:", port)

    except:
        print("SKIP:", port)

print("DONE (All COMs)")
