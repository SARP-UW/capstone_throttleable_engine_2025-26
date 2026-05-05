import RPi.GPIO as GPIO
import time
from .valve import Valve, ValveState

# single valve actuation test

pin = 21
GPIO.setmode(GPIO.BCM)
GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

test_valve = Valve("fmfv", pin, True)

print("Opening valve")
test_valve.set_state(ValveState.OPEN)

time.sleep(10)

print("Closing valve")
test_valve.set_state(ValveState.CLOSED)

time.sleep(10)

print("Pulsing valve for 10 seconds")
test_valve.pulse_valve(10)



GPIO. cleanup()