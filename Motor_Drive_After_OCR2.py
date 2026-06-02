import gpiod
import time

LED_PIN = 24

chip = gpiod.Chip('/dev/gpiochip0')
request = chip.request_lines(
    config={LED_PIN: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)},
    consumer="motor_after_ocr"
)
def main():
    #while(1):
    request.set_value(LED_PIN, gpiod.line.Value.ACTIVE)
    print("ON")
    time.sleep(10)  #used to be 9.25 found this one to line up better with arm 
    request.set_value(LED_PIN, gpiod.line.Value.INACTIVE)
    print("OFF")
    time.sleep(1)  # Sleep for one second
    request.release()
    chip.close()
if __name__ == "__main__":
    main()
