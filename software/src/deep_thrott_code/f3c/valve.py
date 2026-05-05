from __future__ import annotations

from enum import Enum
import time

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

    def __init__(self, valve_id: str, pin: int | None, active_high: bool):
        self.valve_id = valve_id
        self.pin = pin
        self.active_high = active_high
        self.default_state = ValveState.CLOSED if active_high else ValveState.OPEN
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
                        GPIO.output(self.pin, GPIO.HIGH if self.active_high else GPIO.LOW)
                    else:
                        GPIO.output(self.pin, GPIO.LOW if self.active_high else GPIO.HIGH)
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
    def __init__(self, valve_id: str, pin: int | None, active_high: bool):
        super().__init__(valve_id, pin, active_high)

    def set_state(self, new_state: ValveState, pwm: float | None = None):
        if self.state != new_state:
            self.state = new_state
            if new_state == ValveState.OPEN:
                pass
                # placeholder for signal to open valve, pwm = pwm_open
            elif new_state == ValveState.THROTTLING:
                pass
                # placeholder for signal to close valve, pwm = pwm
            else:
                pass
                # placeholder for signal to close valve, pwm = 0

    def throttle(self, angle: float):
        pass
        # placeholder for throttling method, where actual actuation will take place

