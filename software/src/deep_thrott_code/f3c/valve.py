class Valve:

    # define GPIO pin mapping as class variables, maybe tie to ID?

    def __init__(self, valve_id: int, default_state):
        self.id = id
        self.default_state = default_state
        self.state = self.default_state

    def set_state(self, new_state):
        if self.state != new_state:
            self.state = new_state
            # space for signal to pin

class ThrottleValve(Valve):
    def __init__(self, valve_id: int, default_state):
        super().__init__(valve_id, default_state)

    def throttle(self, pwm):
        pass
        # placeholder for throttling method, where actual actuation will take place