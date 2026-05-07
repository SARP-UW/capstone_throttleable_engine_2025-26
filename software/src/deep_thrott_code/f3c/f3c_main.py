try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ModuleNotFoundError:
    GPIO_AVAILABLE = False

import time
from valve import Valve, ValveState
from controller import Controller
from queue import Queue
import threading

# single valve actuation test

pin = 21
GPIO.setmode(GPIO.BCM)
GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

test_command_queue = Queue()
test_ack_queue = Queue()

print("Initializing Controller...")
controller = Controller("test_hardware.yaml", "sequences.yaml", test_command_queue, test_ack_queue)
print("Controller initialized.")
controller_thread = threading.Thread(target=controller.start)
controller_thread.daemon = True
print("Starting controller thread...")
controller_thread.start()
print("Controller thread started.")

print("Single valve actuation command to controller: open")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve",
    "valve_state": "open"
})

time.sleep(5)

print("Single valve actuation command to controller: close")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve",
    "valve_state": "closed"
})

time.sleep(5)

if GPIO_AVAILABLE:
    print("GPIO command high")
    GPIO.output(pin, GPIO.HIGH)

    time.sleep(5)

    print("GPIO command low")
    GPIO.output(pin, GPIO.LOW)

    time.sleep(5)

# time.sleep(10)

# print("Single valve actuation command to controller: pulse for 10 seconds")
# test_command_queue.put("single valve pulse", "test valve", )
# time.sleep(10)



GPIO. cleanup()