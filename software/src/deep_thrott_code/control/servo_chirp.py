import numpy as np
# from debugpy._vendored.pydevd._pydevd_bundle import pydevd_io
from scipy.signal import chirp
import matplotlib.pyplot as plt
import serial
import time

import RPi.GPIO as GPIO

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from f3c.valve import ThrottleValve

TX_ENABLE_PIN = 18

GPIO.setmode(GPIO.BCM)
GPIO.setup(TX_ENABLE_PIN, GPIO.OUT, initial=GPIO.HIGH)

# Parameters
T = 10.0             # Total time in seconds
fs = 1000           # Sampling frequency (Hz)
f0 = 0.01             # Start frequency (Hz)
f1 = 2            # End frequency 1 (Hz)
f2 = 5            # End frequency 2 (Hz)
f3 = 10            # End frequency 3 (Hz)
f4 = 20            # End frequency 4 (Hz)
t = np.linspace(0, T, int(T * fs), endpoint=False)

# Generate linear chirp
# method options: 'linear', 'quadratic', 'logarithmic'
chirp_2hz = chirp(t, f0=f0, t1=T, f1=f1, method='linear')
chirp_5hz = chirp(t, f0=f0, t1=T, f1=f2, method='linear')
chirp_10hz = chirp(t, f0=f0, t1=T, f1=f3, method='linear')
chirp_20hz = chirp(t, f0=f0, t1=T, f1=f4, method='linear')
chirp_angle_2hz = 45*chirp_2hz + 45
chirp_angle_5hz = 45*chirp_5hz + 45
chirp_angle_10hz = 45*chirp_10hz + 45
chirp_angle_20hz = 45*chirp_20hz + 45

# Plot
# plt.plot(t, chirp_angle_10hz)
# plt.title("Linear Chirp Sine Wave")
# plt.xlabel("Time (s)")
# plt.ylabel("Amplitude (Degrees)")
# plt.show()

# start serial
ser = serial.Serial("/dev/ttyS0", baudrate=115200, timeout=1.0)
ser.close()
time.sleep(0.5)
ser.open()

ser.reset_input_buffer()
ser.reset_output_buffer()
time.sleep(0.1)


# define uart helper functions
def _checksum(uart_id, length, cmd, params):
    total = uart_id + length + cmd + sum(params)
    return (~total) & 0xFF

def build_packet(uart_id, cmd, params=[]):
    length = len(params) + 3
    chk = _checksum(uart_id, length, cmd, params)
    return bytes([0x55, 0x55, uart_id, length, cmd] + params + [chk])


def send_packet(packet):
    # pull low to say "i'm bouta transmit"
    GPIO.output(TX_ENABLE_PIN, GPIO.LOW)
    print("Pulled pin low")
    ser.write(packet)
    ser.flush()

    # wait for all bits to clock out of the shift register at 115200 baud
    # (len(packet) bytes * 8 bits/byte) / 115200 + margin
    # time.sleep(len(packet) * 10 / 115200 + 0.0002)
    time.sleep(3)

    # pull high to say "i'm done transmitting yo"
    GPIO.output(TX_ENABLE_PIN, GPIO.HIGH)
    print("Pulled pin high")


def read_response(packet_length, expected_length):
    # get rid of echo with a shorter timeout
    old_timeout = ser.timeout
    ser.timeout = 0.02
    echo = ser.read(packet_length)
    print(f"Echo bytes: {list(echo)}")
    ser.timeout = old_timeout

    # get actual response
    serial_response = ser.read(expected_length)
    print(f"Response bytes: {list(serial_response)}")
    if len(serial_response) == 0:
        print("Timed out - no response received.")
        return None
    return serial_response

# get valve id
print(f"GPIO mode: {GPIO.getmode()}")
print(f"GPIO function of pin {TX_ENABLE_PIN}: {GPIO.gpio_function(TX_ENABLE_PIN)}")
print("Sending valve id request...")
packet = build_packet(0xFE, 14)
print(f"Packet bytes: {list(packet)}")
send_packet(packet)
time.sleep(0.05)
print(f"Bytes waiting: {ser.in_waiting}")

response = read_response(len(packet), 7)
print(f"Response: {response}")

if response is None:
    print("No response received.")
    quit()
else:
    valve_id = response[5]
    print(f"Valve ID: {valve_id}")

# initialize test throttle valve
test_valve = ThrottleValve("test_valve", True, valve_id, ser)

# test open and close servo to 60 deg
test_valve.throttle(60, 2)
time.sleep(2)
print("Valve angle:", test_valve.read_pos())
time.sleep(3)
test_valve.throttle(0, 2)
print("Valve angle:", test_valve.read_pos())
