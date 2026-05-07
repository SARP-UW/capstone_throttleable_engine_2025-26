from __future__ import annotations

from enum import Enum
import time
import serial

try:
    import RPi.GPIO as GPIO  # type: ignore
    GPIO_AVAILABLE = True
except ModuleNotFoundError:
    # Windows/dev-machine friendly stub.
    # On non-Pi systems we still want to import and run the controller in
    # "simulation" without touching GPIO.
    GPIO_AVAILABLE = False

    class _StubGPIO:  # noqa: D401
        OUT = 0
        HIGH = 1
        LOW = 0

        def setup(self, *_args, **_kwargs) -> None:
            return None

        def output(self, *_args, **_kwargs) -> None:
            return None

        def cleanup(self, *_args, **_kwargs) -> None:
            return None

    GPIO = _StubGPIO()  # type: ignore

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
                GPIO.setup(self.pin, GPIO.OUT)
            except Exception:
                # Best-effort: keep simulation runnable.
                pass

    def set_state(self, new_state: ValveState):
        if self.state != new_state:
            self.state = new_state
            if GPIO_AVAILABLE and self.pin is not None:
                try:
                    if new_state == ValveState.OPEN:
                        GPIO.output(self.pin, GPIO.HIGH if self.normally_closed else GPIO.LOW)
                    else:
                        GPIO.output(self.pin, GPIO.LOW if self.normally_closed else GPIO.HIGH)
                except Exception:
                    # Best-effort: keep simulation runnable.
                    pass

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
    def __init__(self, valve_id: str, pin: int | None, normally_closed: bool, uart_id: int, ser: serial.Serial):
        super().__init__(valve_id, None, normally_closed)
        self.uart_id = uart_id
        self.ser = ser

    # do we want this, or is throttle enough?
    def set_state(self, new_state: ValveState, theta: float | None = None):
        if self.state != new_state:
            self.state = new_state
            if new_state == ValveState.OPEN:
                self.throttle(90.0)
            else:
                self.throttle(0.0)

    def throttle(self, angle_deg: float, time_ms):
        """
            Move servo to angle (0-1000 => 0-240°) over time_ms (0-30000ms).
            Moves immediately on receipt.
            Implementation of SERVO_MOVE_TIME_WRITE
            """
        angle_param = int(angle_deg * 1000.0 / 240.0)
        angle_param = max(0, min(1000, angle_param))
        time_ms = max(0, min(30000, time_ms))
        params = [
            angle_param & 0xFF, (angle_param >> 8) & 0xFF,
            time_ms & 0xFF, (time_ms >> 8) & 0xFF
        ]
        self.send_packet(self.build_packet(1, params))

    def read_pos(self):
        self.send_packet(self.build_packet(28))
        response = self.read_response(7)

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

    def _checksum(self, length, cmd, params):
        total = self.uart_id + length + cmd + sum(params)
        return (~total) & 0xFF

    def build_packet(self, cmd, params=[]):
        length = len(params) + 3
        chk = self._checksum(self.uart_id, length, cmd, params)
        return bytes([0x55, 0x55, self.uart_id, length, cmd] + params + [chk])

    def send_packet(self, packet):
        self.ser.write(packet)

    def read_response(self, expected_length):
        return self.ser.read(expected_length)
