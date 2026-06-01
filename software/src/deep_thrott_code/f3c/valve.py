from __future__ import annotations

from enum import Enum
import time
import threading

from scipy.stats import false_discovery_control

# import serial

try:
    import pigpio  # type: ignore
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True

    # Ensure GPIO numbering mode is configured once.
    # We use BCM numbering, so `hardware.yml` pins should be BCM GPIO numbers.
    try:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
    except Exception as exc:
        # Don't force simulation mode here; let setup/output attempts surface
        # the real error (usually permissions) with explicit prints.
        print(f"GPIO init (setmode BCM) failed: {exc!r}")
except ModuleNotFoundError:
    # Windows/dev-machine friendly stub.
    # On non-Pi systems we still want to import and run the controller in
    # "simulation" without touching GPIO.
    GPIO_AVAILABLE = False

computer_sim = False

if computer_sim:
    GPIO_AVAILABLE = False

class ValveState(Enum):
    """
    Defines the states a valve can be in.
    """
    CLOSED = "closed"
    OPEN = "open"
    THROTTLING = "throttling"

class Valve:
    """
    Class which represents an on/off valve, parent for throttle valves.
    """

    def __init__(self, valve_id: str, pin: int | None, normally_closed: bool):
        self.valve_id = valve_id
        self.pin = pin
        self.normally_closed = normally_closed
        self.default_state = ValveState.CLOSED if normally_closed else ValveState.OPEN
        self.state = self.default_state
        # Only touch GPIO when available and wired.
        if GPIO_AVAILABLE and self.pin is not None:
            try:
                GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)
            except Exception:
                # Best-effort: keep simulation runnable.
                pass
            except Exception as exc:
                print(f"GPIO setup failed for valve {self.valve_id} on pin {self.pin}: {exc!r}")
        elif self.pin is None:
            print(f"Valve {self.valve_id}: pin is None (not wired/configured)")
        elif not GPIO_AVAILABLE:
            print(f"Valve {self.valve_id}: RPi.GPIO unavailable; running in simulation mode")

    def get_valve_id(self) -> str:
        return self.valve_id

    def get_state(self) -> ValveState:
        return self.state

    def is_normally_closed(self) -> bool:
        return self.normally_closed

    def set_state(self, new_state: ValveState):
        if self.state != new_state:
            self.state = new_state
            if GPIO_AVAILABLE and self.pin is not None:
                try:
                    if new_state == ValveState.OPEN:
                        level = GPIO.HIGH if self.normally_closed else GPIO.LOW
                    else:
                        level = GPIO.LOW if self.normally_closed else GPIO.HIGH
                    GPIO.output(self.pin, level)
                    print(
                        f"GPIO output valve {self.valve_id} pin {self.pin} -> "
                        f"{'HIGH' if level else 'LOW'} ({new_state.value})"
                    )
                except Exception as exc:
                    print(
                        f"GPIO output failed for valve {self.valve_id} on pin {self.pin} "
                        f"(requested {new_state.value}): {exc!r}"
                    )
            else:
                # for when no rasp pi is connected, print statements instead of GPIO outputs
                if new_state == ValveState.OPEN:
                    print(f"Valve {self.valve_id} is open")
                else:
                    print(f"Valve {self.valve_id} is closed")

    def pulse_valve(self, dt: float):
        if self.state == ValveState.CLOSED:
            self.set_state(ValveState.OPEN)
            time.sleep(dt)
            self.set_state(ValveState.CLOSED)
        else:
            # TODO: send error that valve must be closed to pulse it
            pass

# TODO: add to initialization to set valve to normal state

class ThrottleValve():
    """
    Class which represents a throttleable valve.
    """
    # TODO: add command numbers/lengths from hiwonder datasheet to get rid of magic numbers
    # variables for pin setup for uart
    TX_ENABLE_PIN = 20
    TX_PIN = 14
    RX_PIN = 15
    BAUD = 115200

    # variables from Hiwonder servo bus communication protocol datasheet
    SERVO_MOVE_TIME_WRITE_CMD = 1
    SERVO_MOVE_TIME_WRITE_LEN = 7
    SERVO_POS_READ_CMD = 28
    SERVO_POS_READ_LEN = 3
    SERVO_LOAD_OR_UNLOAD_WRITE_CMD = 31
    SERVO_LOAD_OR_UNLOAD_WRITE_LEN = 4
    SERVO_LOAD_OR_UNLOAD_WRITE_PARAM = 1

    # servo units -> angle conversion values
    SERVO_ANGLE_DEG = 240
    SERVO_ANGLE_PARAM = 1000

    # lock for sending waveforms
    _wave_lock = threading.Lock()

    def __init__(self, valve_id: str, uart_id: int, serial_handle, pi_instance, normally_closed: bool):
        self.valve_id = valve_id
        self.uart_id = uart_id
        self.pi = pi_instance
        self.serial_handle = serial_handle
        self.load_motor()
        self.checksum_found = False
        self.state = ValveState.OPEN
        self.normally_closed = normally_closed


    def is_normally_closed(self) -> bool:
        return self.normally_closed

    def get_valve_id(self) -> str:
        return self.valve_id

    def get_state(self) -> ValveState:
        return self.state

    def set_state(self, new_state: ValveState, theta: float | None = None):
        actuation_time = 0
        if self.state != new_state:
            self.state = new_state

            # angles calibrated for omctv
            if self.valve_id == "omctv":
                if new_state == ValveState.OPEN:
                    self.throttle(75.0, actuation_time)
                else:
                    self.throttle(-15.0, actuation_time)
            # angles calibrated for fmctv
            else:
                if new_state == ValveState.OPEN:
                    self.throttle(110.0, actuation_time)
                else:
                    self.throttle(20.0, actuation_time)

    def pulse_valve(self, dt: float):
        if self.state == ValveState.CLOSED:
            self.set_state(ValveState.OPEN)
            time.sleep(dt)
            self.set_state(ValveState.CLOSED)
        else:
            # TO DO: send error that valve must be closed to pulse it
            pass

    # TODO: make time_s 0.0 by default
    def throttle(self, angle_deg: float, time_s):
        """
            Move servo to angle (0-1000 => 0-240°) over time_ms (0-30000ms).
            Moves immediately on receipt.
            Implementation of SERVO_MOVE_TIME_WRITE
            """
        print(f"Throttling {self.valve_id}")
        time_ms = int(time_s * 1000)
        angle_param = int(angle_deg * self.SERVO_ANGLE_PARAM / self.SERVO_ANGLE_DEG)
        angle_param = max(0, min(1000, angle_param)) # clip between 0 and 1000
        time_ms = max(0, min(30000, time_ms)) # clip between 0 and 30000ms
        params = [
            angle_param & 0xFF, (angle_param >> 8) & 0xFF,
            time_ms & 0xFF, (time_ms >> 8) & 0xFF
        ]
        print(f"Sending packet: {self.build_packet(self.SERVO_MOVE_TIME_WRITE_CMD, params)}")
        self.send_packet(self.build_packet(self.SERVO_MOVE_TIME_WRITE_CMD, params))

    def read_pos(self):
        # build packet to request angle encoder data
        read_pos_packet = self.build_packet(self.SERVO_POS_READ_CMD)

        # get checksum from packet sent
        packet_checksum = read_pos_packet[-1]

        # send packet to request angle encoder data
        self.send_packet(read_pos_packet)

        # get response from servo
        response = self.read_response(packet_checksum, self.SERVO_POS_READ_LEN + 3)

        # if statement validates response is of the correct structure
        if len(response) >= 7 and response[0] == 0x55 and response[1] == 0x55:
            # reassembles the two position bytes into a 16-bit integer
            low = response[5]   # 6th byte is the lower 8 bits
            high = response[6]  # 7th byte is the higher 8 bits

            raw = (high << 8) | low

            # conversion to get correct signed value
            if raw > 32767:
                raw -= 65536

            # converts from servo internal units to degrees
            angle_deg = raw * self.SERVO_ANGLE_DEG / self.SERVO_ANGLE_PARAM
        else:
            angle_deg = 0
        return angle_deg

    # uart helper functions
    def load_motor(self):
        """
        Enable torque output - must be called before servo will move
        """
        params = [self.SERVO_LOAD_OR_UNLOAD_WRITE_PARAM]
        self.send_packet(self.build_packet(self.SERVO_LOAD_OR_UNLOAD_WRITE_CMD, params))

    def _checksum(self, length, cmd, params):
        total = self.uart_id + length + cmd + sum(params)
        return (~total) & 0xFF

    def build_packet(self, cmd, params=[]):
        length = len(params) + 3
        chk = self._checksum(length, cmd, params)
        return bytes([0x55, 0x55, self.uart_id, length, cmd] + params + [chk])

    def send_packet(self, packet):
        bits_total = len(packet) * 10  # 1 Start bit + 8 Data bits + 1 Stop bit = 10 bits per byte
        duration_us = int((bits_total * 1_000_000) / self.BAUD)  # time in microseconds to send all bytes
        margin_us = 20  # margin to prevent clipping the stop bit
        total_wave_time = margin_us + duration_us + margin_us  # total time TX_ENABLE stays low (transmission time with margin before and after)

        self.pi.wave_clear()  # clears last waveform before sending a new one
        self.pi.wave_add_serial(self.TX_PIN, self.BAUD, packet, offset=margin_us)  # adds waveform from packet to staging area

        enable_pulses = [
            # Set TX_ENABLE low, hold for total_wave_time microseconds
            pigpio.pulse(0, 1 << self.TX_ENABLE_PIN, total_wave_time),
            # Set TX_ENABLE high, hold for 0 microseconds (end of wave)
            pigpio.pulse(1 << self.TX_ENABLE_PIN, 0, 0)
        ]
        self.pi.wave_add_generic(enable_pulses)  # adds TX_ENABLE pulses to staging area

        # Create wave id from waveforms in staging area and send
        wave_id = self.pi.wave_create()
        print(f"wave_id: {wave_id}")
        self.pi.wave_send_once(wave_id)

        # Polls until DMA is done
        while self.pi.wave_tx_busy():
            time.sleep(0.001)

        # Frees up memory
        self.pi.wave_delete(wave_id)

        return len(packet)

    def read_response(self, packet_checksum, expected_length):
        checksum_found = False
        # drain the echos
        while not checksum_found:
            count, echo_byte = self.pi.serial_read(self.serial_handle, 1)
            if echo_byte == packet_checksum:
                checksum_found = True

        # read the response
        time.sleep(0.02)
        count, serial_response = self.pi.serial_read(self.serial_handle, expected_length)
        print(f"Response bytes: {list(serial_response)}")

        if count == 0:
            print("Timed out - no response received.")
            return None
        return serial_response
    

class WaterValvePWM:
    """
    Simple PWM-controlled servo valve.
    Maps 500-2500us pulse width to 0°-180° angle.
    """
    PWM_FREQUENCY = 50  # Hz (20ms period for standard RC servo)
    MIN_PULSE_US = 500
    MAX_PULSE_US = 2500
    MAX_ANGLE_DEG = 180
    
    def __init__(self, valve_id: str, pin: int, normally_closed: bool, pi_instance):
        self.valve_id = valve_id
        self.pin = pin
        self.current_angle = 0.0
        self.normally_closed = normally_closed
        self.state = ValveState.CLOSED
        self.pi = pi_instance
        
        if GPIO_AVAILABLE:
            try:
                self.pi.hardware_PWM(self.pin, self.PWM_FREQUENCY, 0)
                print(f"WaterValvePWM {self.valve_id}: initialized on pin {self.pin}")
            except Exception as exc:
                print(f"WaterValvePWM {self.valve_id}: PWM setup failed: {exc!r}")
        else:
            print(f"WaterValvePWM {self.valve_id}: running in simulation mode")
    
    def set_angle(self, angle_deg: float):
        """Set servo angle (0-180 degrees)."""

        angle_deg = max(0.0, min(self.MAX_ANGLE_DEG, angle_deg))
        self.current_angle = angle_deg
        
        # Calculate pulse width: linear interpolation from MIN to MAX
        pulse_us = self.MIN_PULSE_US + (angle_deg / self.MAX_ANGLE_DEG) * (self.MAX_PULSE_US - self.MIN_PULSE_US)
        
        # Convert to duty cycle (0-1000000 for pigpio hardware_PWM)
        period_us = 1_000_000 / self.PWM_FREQUENCY
        duty_cycle = int((pulse_us / period_us) * 1_000_000)
        
        if GPIO_AVAILABLE:
            try:
                self.pi.hardware_PWM(self.pin, self.PWM_FREQUENCY, duty_cycle)
            except Exception as exc:
                print(f"WaterValvePWM {self.valve_id}: PWM write failed: {exc!r}")
        else:
            print(f"WaterValvePWM {self.valve_id}: set to {angle_deg:.1f}° ({pulse_us:.0f}us)")

    def set_state(self, new_state: ValveState):
        if new_state == ValveState.OPEN:
            self.set_angle(0.0)
        else:
            self.set_angle(90.0)

        self.state = new_state

    def get_state(self) -> ValveState:
        return self.state

    def pulse_valve(self, dt: float):
        if self.state == ValveState.CLOSED:
            self.set_state(ValveState.OPEN)
            time.sleep(dt)
            self.set_state(ValveState.CLOSED)
        else:
            # TO DO: send error that valve must be closed to pulse it
            pass

    def is_normally_closed(self) -> bool:
        return self.normally_closed

    def get_valve_id(self) -> str:
        return self.valve_id
