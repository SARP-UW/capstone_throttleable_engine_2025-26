from .valve import Valve, ThrottleValve, ValveState

# Creates

class Controller:
    def __init__(self, valve_list: list[Valve]):
        self.valve_list = valve_list
