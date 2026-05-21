import numpy as np
# from debugpy._vendored.pydevd._pydevd_bundle import pydevd_io
from scipy.signal import chirp
# import matplotlib.pyplot as plt
import serial
import time

import pigpio
pi = pigpio.pi()
if not pi.connected:
    print("Failed to connect to pigpiod")
    exit()

# TODO: evaluate whether this is needed
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from f3c.valve import ThrottleValve

TX_ENABLE_PIN = 18
TX_PIN = 14
RX_PIN = 15     # check this!
BAUD = 115200

# TX_ENABLE pin setup
pi.set_mode(TX_ENABLE_PIN, pigpio.OUTPUT)
pi.set_mode(TX_PIN, pigpio.OUTPUT)
pi.write(TX_ENABLE_PIN, 1)     # start in receive mode

# Open pigpio serial port for reading responses
serial_handle = pi.serial_open("/dev/ttyS0", BAUD)

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


# define uart helper functions
def _checksum(uart_id, length, cmd, params):
    total = uart_id + length + cmd + sum(params)
    return (~total) & 0xFF

def build_packet(uart_id, cmd, params=[]):
    length = len(params) + 3
    chk = _checksum(uart_id, length, cmd, params)
    return bytes([0x55, 0x55, uart_id, length, cmd] + params + [chk])

def send_packet(packet):
    bits_total = len(packet) * 10        # 1 Start bit + 8 Data bits + 1 Stop bit = 10 bits per byte
    duration_us = int((bits_total * 1_000_000) / BAUD)           # time in microseconds to send all bytes
    margin_us = 10          # margin to prevent clipping the stop bit
    total_wave_time = margin_us + duration_us + margin_us          # total time TX_ENABLE stays low (transmission time with margin before and after)

    pi.wave_clear()      # clears last waveform before sending a new one
    pi.wave_add_serial(TX_PIN, BAUD, packet, offset=margin_us)        # adds waveform from packet to staging area

    enable_pulses = [
        # Set TX_ENABLE low, hold for total_wave_time microseconds
        pigpio.pulse(0, 1 << TX_ENABLE_PIN, total_wave_time),
        # Set TX_ENABLE high, hold for 0 microseconds (end of wave)
        pigpio.pulse(1 << TX_ENABLE_PIN, 0, 0)
    ]
    pi.wave_add_generic(enable_pulses)      # adds TX_ENABLE pulses to staging area

    # Create wave id from waveforms in staging area and send
    wave_id = pi.wave_create()
    pi.wave_send_once(wave_id)

    # Polls until DMA is done
    while pi.wave_tx_busy():
        time.sleep(0.001)

    # Frees up memory
    pi.wave_delete(wave_id)

    return len(packet)


def read_response(packet_checksum, expected_length):
    # checksum_found = False
    # # drain the echo
    # while not checksum_found:
    #     count, echo_byte = pi.serial_read(serial_handle, 1)
    #     if echo_byte == packet_checksum:
    #         checksum_found = True

    count, echo = pi.serial_read(serial_handle, 5)
    print(f"Echo bytes: {list(echo)}")

    # read the response
    time.sleep(0.02)
    count, serial_response = pi.serial_read(serial_handle, expected_length)
    print(f"Response bytes: {list(serial_response)}")

    if count == 0:
        print("Timed out - no response received.")
        return None
    return serial_response

# valve_id_assignment_packet = build_packet(0xFE, 13, [2])
# send_packet(valve_id_assignment_packet)

# get valve id
print("Sending valve id request...")
packet = build_packet(0xFE, 14)
print(f"Packet bytes: {list(packet)}")
send_packet(packet)
time.sleep(0.1)

response = read_response(len(packet), 7)
print(f"Response: {response}")

if response is None:
    print("No response received.")
    pi.serial_close(serial_handle)
    pi.stop()
    exit()

valve_id = response[5]
print(f"Valve ID: {valve_id}")

# # initialize test throttle valve
# test_valve_naked = ThrottleValve("test_valve", 1, serial_handle)
# test_valve_decent = ThrottleValve("test_valve2", 2, serial_handle)
#
# while True:
#     # test open and close servo to 90 deg
#     test_valve.throttle(90, 2)
#     time.sleep(2)
#     print("Valve angle:", test_valve.read_pos())
#     time.sleep(3)
#     test_valve.throttle(0, 2)
#     time.sleep(2)
#     print("Valve angle:", test_valve.read_pos())
#     time.sleep(3)

pi.serial_close(serial_handle)
pi.stop()
