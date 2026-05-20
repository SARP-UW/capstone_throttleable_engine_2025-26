from __future__ import annotations

from enum import Enum
import time
# import serial

try:
    import pigpio  # type: ignore
    import RPi.GPIO as GPIO
    pi = pigpio.pi()
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

    def get_state(self) -> ValveState:
        return self.state

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
            # TO DO: send error that valve must be closed to pulse it
            pass

class ThrottleValve(Valve):
    """
    Class which represents a throttleable valve, inherits from Valve.
    """
    # TODO: add command numbers/lengths from hiwonder datasheet to get rid of magic numbers
    TX_ENABLE_PIN = 18
    TX_PIN = 14
    RX_PIN = 15
    BAUD = 115200

    def __init__(self, valve_id: str, normally_closed: bool, uart_id: int, serial_handle):
        super().__init__(valve_id, None, normally_closed)
        self.uart_id = uart_id
        self.serial_handle = serial_handle
        self.load_motor()


    # do we want this, or is throttle enough?
    def set_state(self, new_state: ValveState, theta: float | None = None):
        if self.state != new_state:
            self.state = new_state
            if new_state == ValveState.OPEN:
                self.throttle(90.0, 0.5)
            else:
                self.throttle(0.0, 0.5)

    def throttle(self, angle_deg: float, time_s):
        """
            Move servo to angle (0-1000 => 0-240°) over time_ms (0-30000ms).
            Moves immediately on receipt.
            Implementation of SERVO_MOVE_TIME_WRITE
            """
        time_ms = int(time_s * 1000)
        angle_param = int(angle_deg * 1000.0 / 240.0)
        angle_param = max(0, min(1000, angle_param))
        time_ms = max(0, min(30000, time_ms))
        params = [
            angle_param & 0xFF, (angle_param >> 8) & 0xFF,
            time_ms & 0xFF, (time_ms >> 8) & 0xFF
        ]
        self.send_packet(self.build_packet(1, params))

    def read_pos(self):
        packet_length = self.send_packet(self.build_packet(28))
        response = self.read_response(packet_length, 8)

        if len(response) >= 7 and response[0] == 0x55 and response[1] == 0x55:
            low = response[5]   # 6th byte is the lower 8 bits
            high = response[6]  # 7th byte is the higher 8 bits

            raw = (high << 8) | low

            if raw > 32767:
                raw -= 65536

            angle_deg = raw * 240 / 1000
        else:
            angle_deg = 0
        return angle_deg

    # uart helper functions
    def load_motor(self):
        """
        Enable torque output - must be called before servo will move
        """
        params = [1]
        self.send_packet(self.build_packet(31, params))

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

        pi.wave_clear()  # clears last waveform before sending a new one
        pi.wave_add_serial(self.TX_PIN, self.BAUD, packet, offset=margin_us)  # adds waveform from packet to staging area

        enable_pulses = [
            # Set TX_ENABLE low, hold for total_wave_time microseconds
            pigpio.pulse(0, 1 << self.TX_ENABLE_PIN, total_wave_time),
            # Set TX_ENABLE high, hold for 0 microseconds (end of wave)
            pigpio.pulse(1 << self.TX_ENABLE_PIN, 0, 0)
        ]
        pi.wave_add_generic(enable_pulses)  # adds TX_ENABLE pulses to staging area

        # Create wave id from waveforms in staging area and send
        wave_id = pi.wave_create()
        pi.wave_send_once(wave_id)

        # Polls until DMA is done
        while pi.wave_tx_busy():
            time.sleep(0.001)

        # Frees up memory
        pi.wave_delete(wave_id)

        return len(packet)

    def read_response(self, packet_length, expected_length):

        # drain the echo
        time.sleep(0.02)
        count, echo = pi.serial_read(self.serial_handle, packet_length)
        print(f"Echo bytes: {list(echo)}")

        # read the response
        time.sleep(0.02)
        count, serial_response = pi.serial_read(self.serial_handle, expected_length)
        print(f"Response bytes: {list(serial_response)}")

        if count == 0:
            print("Timed out - no response received.")
            return None
        return serial_response
