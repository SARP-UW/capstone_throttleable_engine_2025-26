import numpy as np
from scipy.signal import chirp
import matplotlib.pyplot as plt
import serial
import time

from f3c.controller import Controller
from f3c.valve import ThrottleValve

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
plt.plot(t, chirp_angle_10hz)
plt.title("Linear Chirp Sine Wave")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude (Degrees)")
plt.show()

# start serial
ser = serial.Serial("/dev/ttyACM0", baudrate=115200, timeout=0.1)

# define uart helper functions
def _checksum(uart_id, length, cmd, params):
    total = uart_id + length + cmd + sum(params)
    return (~total) & 0xFF

def build_packet(uart_id, cmd, params=None):
    length = len(params) + 3
    chk = _checksum(length, cmd, params)
    return bytes([0x55, 0x55, uart_id, length, cmd] + params + [chk])

def send_packet(packet):
    ser.write(packet)

def read_response(expected_length):
    return ser.read(expected_length)

# get valve id
send_packet(build_packet(0xFE, 14))
response = read_response(6)
valve_id = response[5]

# initialize test throttle valve
test_valve = ThrottleValve("test_valve", None, True, valve_id, ser)

# test open and close servo to 60 deg
test_valve.throttle(60, 2)
time.sleep(5)
test_valve.throttle(0, 2)
