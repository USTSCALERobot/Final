import gpiod
import time

# # Set up the GPIO mode
# GPIO.setmode(GPIO.BCM)
# 
LED_PIN = 24
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(LED_PIN)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT)

def main():
    #while(1):
    led_line.set_value(1)
    print("ON")
    time.sleep(4.25)
    led_line.set_value(0)
    print("OFF")
    time.sleep(1)  # Sleep for one second
    led_line.release()
if __name__ == "__main__":
    main()
