from .valve import Valve, ThrottleValve, ValveState
import queue
from enum import Enum

class State(Enum):
    IDLE = "idle"
    FILL = "fill"
    FIRE = "fire"
    THROTTLE = "throttle"
    SAFE = "safe"

class TransitionAction(Enum):
    END = "end"                # when hitting the end of a sequence
    ABORT = "abort"            # when the user aborts a sequence
    START = "start"            # when a sequence starts
    AUTO = "auto"              # when automatically going to the next step (no user input)
    EXIT_SAFE = "exit_safe"    # when the system is allowed to exit safe mode (must receive user input)

class Controller:
    """
    Controller class to manage sequencing, receives sequences to execute from GUI and talks to valve classes.
    """
    def __init__(self, valve_list: list[Valve]):
        self.valve_list = valve_list
        self.q = queue.Queue()
        self.transitions = self._build_transitions()

    def _loop(self):
        while True:
            gui_input = self.q.get()
            if gui_input is None:
                break
            self.execute_action(gui_input)

    @staticmethod
    def _build_transitions(self):
        """
        Key: current state, transition action
        Value: next state
        """""
        return {

        }


    def execute_action(self, action_list: list[tuple[int, ValveState]]):
        for action in action_list:
            pass

    def submit(self, gui_input):
        self.q.put(gui_input)

    def shutdown(self):
        self.q.put(None)