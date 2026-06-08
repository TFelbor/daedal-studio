G28 ; home all axes
G1 Z5 F5000 ; lift nozzle
G1 X10 Y10 F5000 ; move to X10 Y10
M104 S0 ; turn off temperature
M140 S0 ; turn off heatbed
M107 ; turn off fan
G28 X0 Y0 ; home X and Y
M84 ; disable motors
