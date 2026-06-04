import os
import sys
import pigpio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from deep_thrott_code.f3c.valve import ThrottleValve

pi = pigpio.pi()
if not pi.connected:
    print("Failed to connect to pigpiod")
    exit(1)

TX_ENABLE_PIN = 20 
TX_PIN = 14
RX_PIN = 15 
BAUD = 115200

FMCTV_ID = 1
OMCTV_ID = 2

# TX_ENABLE pin setup
pi.set_mode(TX_ENABLE_PIN, pigpio.OUTPUT)
pi.set_mode(TX_PIN, pigpio.OUTPUT)
pi.write(TX_ENABLE_PIN, 1)     # start in receive mode

# Open pigpio serial port for reading responses
serial_handle = pi.serial_open("/dev/ttyS0", BAUD)

throttle_valve = ThrottleValve("FMCTV", FMCTV_ID, serial_handle, pi, True)


try:
    while True:
        user_input = input("Enter angle 0-180 (q to quit): ").strip()
        if user_input.lower() in ("q", "quit", "exit"):
            break

        try:
            angle = float(user_input)
        except ValueError:
            print("Please enter a valid number.")
            continue

        angle = max(0.0, min(180.0, angle))
        throttle_valve.throttle(angle, 0.0)
        print(f"Set throttle valve to {angle:.1f}°")

except KeyboardInterrupt:
    print("\nStopped by Ctrl+C")

finally:
    print("Cleaning up...")
    try:
        if 'serial_handle' in globals():
            pi.serial_close(serial_handle)
    except Exception as exc:
        print(f"Failed to close serial handle: {exc!r}")

    try:
        pi.stop()
    except Exception as exc:
        print(f"Failed to stop pigpio: {exc!r}")

    print("Cleanup complete.")






