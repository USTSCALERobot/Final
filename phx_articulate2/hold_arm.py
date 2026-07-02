#sets gripper to hold chip so that visual data collection can begin
import phx
import Pick_coord_from_crop_txt3 as pc
from time import sleep

#open and close in a loop removes need to re run program repeatedly
run = True
while run == True:
    try:
        phx.gripper2.set_position(300) #start open
        sleep(3)
        phx.gripper2.set_position(120) #120 is generally a good position for holding an IC
        sleep(5)
    except KeyboardInterrupt:
        break
