from enum import Enum

class ValveState(Enum):
    """
    Defines the states a valve can be in.
    """
    CLOSED = "closed"
    OPEN = "open"

class Valve:
    """
    Class which represents an on/off valve, parent for throttle valves.
    """
    # define GPIO pin mapping as class variables, maybe tie to ID?

    def __init__(self, valve_id: int, default_state: ValveState):
        self.id = id
        self.default_state = default_state
        self.state = self.default_state

    def set_state(self, new_state):
        if self.state != new_state:
            self.state = new_state
            # placeholder for signal to pin
            # need to log actuation, return to controller or log here?

class ThrottleValve(Valve):
    """
    Class which represents a throttleable valve, inherits from Valve.
    """
    def __init__(self, valve_id: int, default_state, pwm_open: float):
        super().__init__(valve_id, default_state)

    def open(self):
        pass
        # placeholder for signal to open valve, use pwm_open

    def throttle(self, pwm):
        pass
        # placeholder for throttling method, where actual actuation will take place

