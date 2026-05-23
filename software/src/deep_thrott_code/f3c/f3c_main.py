try:
    import RPi.GPIO as GPIO
    import pigpio
    GPIO_AVAILABLE = True
except ModuleNotFoundError:
    GPIO_AVAILABLE = False

import time
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

print("Actuating valve 1")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve1",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 2")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve2",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 3")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve3",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 4")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve4",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 5")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve5",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 6")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve6",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 7")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve7",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 8")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve8",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 9")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve9",
    "state": "open"
})

time.sleep(1)

print("Actuating valve 10")
test_command_queue.put({
    "type": "set_valve",
    "valve_id": "test_valve10",
    "state": "open"
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
