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

test_command_queue = Queue()
test_ack_queue = Queue()

print("Initializing Controller...")
controller = Controller("test_hardware.yaml", "test_sequences.yaml", test_command_queue, test_ack_queue)
print("Controller initialized.")
controller_thread = threading.Thread(target=controller.start)
controller_thread.daemon = True
print("Starting controller thread...")
controller_thread.start()
print("Controller thread started.")

print("Sending fill sequence command to controller...")
test_command_queue.put({
    "type": "fill",
})

# print("Single valve actuation command to controller: open")
# test_command_queue.put({
#     "type": "set_valve",
#     "valve_id": "test_valve",
#     "valve_state": "open"
# })
#
# time.sleep(5)
#
# print("Single valve actuation command to controller: close")
# test_command_queue.put({
#     "type": "set_valve",
#     "valve_id": "test_valve",
#     "valve_state": "closed"
# })

time.sleep(5)

# if GPIO_AVAILABLE:
#     print("GPIO command high")
#     GPIO.output(pin, GPIO.HIGH)
#
#     time.sleep(5)
#
#     print("GPIO command low")
#     GPIO.output(pin, GPIO.LOW)
#
#     time.sleep(5)
#     GPIO.cleanup()

# time.sleep(10)

# print("Single valve actuation command to controller: pulse for 10 seconds")
# test_command_queue.put("single valve pulse", "test valve", )
# time.sleep(10)
