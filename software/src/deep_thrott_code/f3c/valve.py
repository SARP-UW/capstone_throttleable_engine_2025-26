from enum import Enum
import RPi.GPIO as GPIO

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

    def __init__(self, valve_id: int, pin: int, active_high: bool):
        self.valve_id = valve_id
        self.pin = pin
        self.active_high = active_high
        self.default_state = ValveState.CLOSED if active_high else ValveState.OPEN
        self.state = self.default_state
        GPIO.setup(pin, GPIO.OUT)

    def set_state(self, new_state: ValveState):
        if self.state != new_state:
            self.state = new_state
            if new_state == ValveState.OPEN:
                GPIO.output(self.pin, GPIO.HIGH if self.active_high else GPIO.LOW)
                # log actuation
                pass
            else:
                GPIO.output(self.pin, GPIO.LOW if self.active_high else GPIO.HIGH)
                # log actuation
                pass

    def pulse_valve(self, time: float):
        # TO DO: implement valve pulse functionality
        pass

class ThrottleValve(Valve):
    """
    Class which represents a throttleable valve, inherits from Valve.
    """
    def __init__(self, valve_id: int, default_state, pwm_open: float):
        super().__init__(valve_id, default_state)

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

