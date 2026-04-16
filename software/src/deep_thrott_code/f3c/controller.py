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
    END = "end"                  # when hitting the end of a sequence
    ABORT = "abort"              # when the user aborts a sequence
    START_FILL = "start_fill"    # when a fill sequence starts
    START_FIRE = "start_fire"    # when a fire sequences starts
    AUTO = "auto"                # when automatically going to the next step (no user input)
    EXIT_SAFE = "exit_safe"      # when the system is allowed to exit safe mode (must receive user input)

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
        Defines the allowed transitions between states. Provided the current state and the action that will be executed, 
        the dict provides what next state the system should enter.
        
        Key: (current state, transition action)
        Value: next state
        """""
        return {
            (State.IDLE, TransitionAction.START_FILL): State.FILL,
            (State.IDLE, TransitionAction.START_FIRE): State.FIRE,
            (State.FILL, TransitionAction.END): State.IDLE,
            (State.FILL, TransitionAction.ABORT): State.SAFE,
            (State.FIRE, TransitionAction.END): State.IDLE,
            (State.FIRE, TransitionAction.ABORT): State.SAFE,
            (State.FIRE, TransitionAction.AUTO): State.THROTTLE,
            (State.THROTTLE, TransitionAction.AUTO): State.FIRE,
            (State.SAFE, TransitionAction.EXIT_SAFE): State.IDLE,
        }


    def execute_action(self, action_list: list[tuple[int, ValveState]]):
        for action in action_list:
            pass

    def submit(self, gui_input):
        self.q.put(gui_input)

    def shutdown(self):
        self.q.put(None)