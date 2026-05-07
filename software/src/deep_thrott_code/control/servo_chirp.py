import numpy as np
from scipy.signal import chirp
import matplotlib.pyplot as plt
import serial
import time
import csv

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
import numpy as np
import matplotlib.pyplot as plt
import csv
import time

# ---------------------------------------------------------
# CSV FILE SETUP
# ---------------------------------------------------------

# Step response CSV (60° → hold → 0°)
csv_step = open("step_response_log.csv", "w", newline="")
step_writer = csv.writer(csv_step)
step_writer.writerow(["time_s", "commanded_deg", "measured_deg"])

# Multi-step CSV (0→10→30→60→0)
csv_multi = open("multi_step_log.csv", "w", newline="")
multi_writer = csv.writer(csv_multi)
multi_writer.writerow(["time_s", "commanded_deg", "measured_deg"])

# Chirp test CSV
csv_chirp = open("chirp_log.csv", "w", newline="")
chirp_writer = csv.writer(csv_chirp)
chirp_writer.writerow(["time_s", "commanded_deg", "measured_deg"])

# Raw UART packet log
csv_uart = open("uart_raw_log.csv", "w", newline="")
uart_writer = csv.writer(csv_uart)
uart_writer.writerow(["time_s", "packet_hex"])


# ---------------------------------------------------------
# UART POLLING FUNCTION (logs raw packets)
# ---------------------------------------------------------

def poll_servo_position(global_start):
    """
    Sends UART command 28 to request servo position.
    Logs the raw packet to uart_raw_log.csv.
    Returns measured angle (or NaN if packet incomplete).
    """

    send_packet(build_packet(valve_id, 28))
    resp = read_response(7)

    # Log raw packet as hex string
    packet_hex = resp.hex(" ")
    t_now = time.time() - global_start
    uart_writer.writerow([t_now, packet_hex])

    if len(resp) >= 6:
        return resp[5]
    else:
        return np.nan


# ---------------------------------------------------------
# RUN A TIMED COMMAND (for step response)
# ---------------------------------------------------------

def run_step_segment(target_angle, duration_s, global_start, writer):
    """
    Commands the servo to a fixed angle and logs measured position
    for 'duration_s' seconds into the provided CSV writer.
    """

    test_valve.throttle(target_angle, 0)
    segment_start = time.time()

    while time.time() - segment_start < duration_s:
        measured = poll_servo_position(global_start)
        t_now = time.time() - global_start
        writer.writerow([t_now, target_angle, measured])


# ---------------------------------------------------------
# NEW: MULTI-STEP TEST (0→10→30→60→0)
# ---------------------------------------------------------

def run_multi_step_test(global_start):
    """
    Runs a sequence of 0°, 10°, 30°, 60°, 0°,
    each held for 2 seconds, and logs to multi_step_log.csv.
    """

    sequence = [0, 10, 30, 60, 0]
    hold_time = 2.0

    for angle in sequence:
        run_step_segment(angle, hold_time, global_start, multi_writer)


# ---------------------------------------------------------
# MAIN EXPERIMENT
# ---------------------------------------------------------

global_start = time.time()

# 1) Step to 60° for 5 seconds
run_step_segment(60, 5, global_start, step_writer)

# 2) Step back to 0° for 2 seconds
run_step_segment(0, 2, global_start, step_writer)

# 3) NEW multi-step test
run_multi_step_test(global_start)

# 4) Chirp test
for commanded in chirp_angle_10hz:
    measured = poll_servo_position(global_start)
    t_now = time.time() - global_start
    chirp_writer.writerow([t_now, float(commanded), measured])


# Close all CSV files
csv_step.close()
csv_multi.close()
csv_chirp.close()
csv_uart.close()


# ---------------------------------------------------------
# PLOT RESULTS AFTER LOGGING
# ---------------------------------------------------------

# Load step response
step_data = np.genfromtxt("step_response_log.csv", delimiter=",", skip_header=1)
step_t = step_data[:, 0]
step_cmd = step_data[:, 1]
step_meas = step_data[:, 2]

# Load multi-step response
multi_data = np.genfromtxt("multi_step_log.csv", delimiter=",", skip_header=1)
multi_t = multi_data[:, 0]
multi_cmd = multi_data[:, 1]
multi_meas = multi_data[:, 2]

# Load chirp response
chirp_data = np.genfromtxt("chirp_log.csv", delimiter=",", skip_header=1)
chirp_t = chirp_data[:, 0]
chirp_cmd = chirp_data[:, 1]
chirp_meas = chirp_data[:, 2]

# Plot step response
plt.figure(figsize=(10,5))
plt.plot(step_t, step_cmd, label="Commanded (Step)")
plt.plot(step_t, step_meas, label="Measured (Step)")
plt.xlabel("Time (s)")
plt.ylabel("Angle (deg)")
plt.title("Step Response: 60° → 0°")
plt.legend()
plt.grid(True)

# Plot multi-step response
plt.figure(figsize=(10,5))
plt.plot(multi_t, multi_cmd, label="Commanded (Multi-Step)")
plt.plot(multi_t, multi_meas, label="Measured (Multi-Step)")
plt.xlabel("Time (s)")
plt.ylabel("Angle (deg)")
plt.title("Multi-Step Response: 0° → 10° → 30° → 60° → 0°")
plt.legend()
plt.grid(True)

# Plot chirp response
plt.figure(figsize=(10,5))
plt.plot(chirp_t, chirp_cmd, label="Commanded (Chirp)")
plt.plot(chirp_t, chirp_meas, label="Measured (Chirp)")
plt.xlabel("Time (s)")
plt.ylabel("Angle (deg)")
plt.title("Chirp Response")
plt.legend()
plt.grid(True)

plt.show()
