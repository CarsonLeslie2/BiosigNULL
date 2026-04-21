
"Check PSU ports"
"Running this will iterate through ports, adding a delay to evaluate COMs"

import time
import serial

BAUD = 9600
TERMINATOR = "\r\n"   
TIMEOUT = 1.0

for n in range(3, 22): # adjust as needed, cycle through all COM values. 
    port = f"COM{n}"
    try:
        psu = serial.Serial(port, BAUD, timeout=TIMEOUT, write_timeout=TIMEOUT)
        
        time.sleep(1.0)

        psu.write(("VSET1:1.00" + TERMINATOR).encode("ascii")); psu.flush() # turn on. 
        print("Turned on:", port)
       
        time.sleep(10.0)  # 10 seconds to check which coil is on. 
        
        psu.write(("VSET1:0.00" + TERMINATOR).encode("ascii")); psu.flush()  # turn off
        psu.write(("ISET1:0.000" + TERMINATOR).encode("ascii")); psu.flush()
        psu.write(("OUT0" + TERMINATOR).encode("ascii")); psu.flush()

        psu.close()
        print("KILLED:", port)

    except:
        print("SKIP:", port)

print("DONE (COM3..COM23)")
