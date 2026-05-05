import RPi.GPIO as GPIO
import time
from valve import Valve, ValveState
from controller import Controller
from queue import Queue

# single valve actuation test

pin = 21
GPIO.setmode(GPIO.BCM)
GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

test_command_queue = Queue()
test_ack_queue = Queue()

controller = Controller("config/test_hardware.yaml", "software/src/deep_thrott_code/config/sequences.yaml", test_command_queue, test_ack_queue)
controller.start()

print("Single valve actuation command to controller: open")
test_command_queue.put(("single valve actuation", "test valve", ValveState.OPEN))

time.sleep(10)

print("Single valve actuation command to controller: close")
test_command_queue.put(("single valve actuation", "test valve", ValveState.CLOSED))

# time.sleep(10)

# print("Single valve actuation command to controller: pulse for 10 seconds")
# test_command_queue.put("single valve pulse", "test valve", )
# time.sleep(10)



GPIO. cleanup()