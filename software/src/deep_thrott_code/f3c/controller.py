from .valve import Valve, ThrottleValve, ValveState
import queue
from enum import Enum
import yaml
import threading

class State(Enum):
    IDLE = "idle"
    FILL = "fill"
    FIRE = "fire"
    THROTTLE = "throttle"
    SAFE = "safe"

class TransitionAction(Enum):
    """
    Define the valid actions that can be taken. GUI can provide these in the form of strings.
    """
    END = "end"                  # when hitting the end of a sequence
    ABORT = "abort"              # when the user aborts a sequence
    FILL = "fill"    # when a fill sequence starts
    FIRE = "fire"    # when a fire sequences starts
    AUTO = "auto"                # when automatically going to the next step (no user input)
    EXIT_SAFE = "exit_safe"      # when the system is allowed to exit safe mode (must receive user input)

class Controller:
    """
    Controller class to manage sequencing, receives sequences to execute from GUI and talks to valve classes.
    """

    def __init__(self, hardware_config_path: str, sequence_config_path: str):
        self.sequence_config_path = sequence_config_path
        self.hardware_config_path = hardware_config_path
        self.q = queue.Queue()
        self.transitions = self._build_transitions()
        self.sequences = self._build_sequences(sequence_config_path)
        self.actuator_list = self._build_actuator_list(hardware_config_path)
        self.state = State.IDLE
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            gui_input = self.q.get()
            if gui_input is None:
                break
            self._execute_action(gui_input)

    def get_state(self):
        return self.state

    def _execute_action(self, action: str, valve_id=None, valve_state=None):
        """
        Method for executing any type of action.
        Args:
            action (str): action to execute, comes from GUI
            valve_id (int): valve id of the valve for single valve actuation, None by default
            valve_state (ValveState): valve state of the valve for single valve actuation, None by default
        """
        # if trying to fill or fire
        if action in (State.FILL.value, State.FIRE.value):
            transition_key = (self.state, TransitionAction(action))

            # if desired action is a valid, defined transition from current state
            if transition_key in self.transitions:

                # update system state to reflect command
                sequence_state = self.transitions.get(transition_key)
                self.state = sequence_state

                # loop through each step in sequence
                sequence = self.sequences.get(action)
                for step in sequence.get("steps"):

                    # check state at each step to catch aborts
                    if self.state == sequence_state:
                        valve_id = step.get("valve_id")
                        current_valve = self.actuator_list.get(valve_id)


    def submit(self, gui_input):
        self.q.put(gui_input)

    def shutdown(self):
        self.q.put(None)

    @staticmethod
    def _build_transitions() -> dict[tuple[State, TransitionAction], State]:
        """
        Defines the allowed transitions between states. Provided the current state and the action that will be executed, 
        the dict provides what next state the system should enter.
        
        Key: (current state, transition action)
        Value: next state
        """""
        return {
            (State.IDLE, TransitionAction.FILL): State.FILL,
            (State.IDLE, TransitionAction.FIRE): State.FIRE,
            (State.FILL, TransitionAction.END): State.IDLE,
            (State.FILL, TransitionAction.ABORT): State.SAFE,
            (State.FIRE, TransitionAction.END): State.IDLE,
            (State.FIRE, TransitionAction.ABORT): State.SAFE,
            (State.FIRE, TransitionAction.AUTO): State.THROTTLE,
            (State.THROTTLE, TransitionAction.AUTO): State.FIRE,
            (State.SAFE, TransitionAction.EXIT_SAFE): State.IDLE,
        }

    @staticmethod
    def _build_sequences(sequence_config_path: str):
        """
        Builds the fill and fire sequences based on the sequences config file.

        Args:
            sequence_config_path (str): path to the sequences config file
        """

        with open(sequence_config_path, "r") as f:
            sequence_config = yaml.safe_load(f)
            sequences = sequence_config.get("sequences")

            sequence_dict = {s["name"]: s for s in sequences}
        return sequence_dict

    @staticmethod
    def _build_actuator_list(hardware_config_path: str):
        """
        Builds the actuator list based on the hardware config.

        Args:
            hardware_config_path (str): path to the hardware config file
        """

        with open(hardware_config_path, "r") as f:
            hardware_config = yaml.safe_load(f)
            actuator_info_list = hardware_config.get("actuators").get("valves")
            actuator_list = {}
            for valve_id, actuator_info in actuator_info_list.items():
                actuator_list[valve_id] = Valve(valve_id, actuator_info.get("default_state"), actuator_info.get("pin"))
        return actuator_list
