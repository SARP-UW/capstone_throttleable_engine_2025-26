from __future__ import annotations
from collections import deque
import queue
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any
import yaml
from .valve import Valve, ValveState

class State(Enum):
    IDLE = "idle"
    FILL = "fill"
    FIRE = "fire"
    THROTTLE = "throttle"
    ABORT = "abort"

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

class StepStatus(Enum):
    READY = "ready"
    WAITING_USER = "waiting_user"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ABORTED = "aborted"

class Controller:
    """
    Controller class to manage sequencing, receives sequences to execute from GUI and talks to valve classes.
    """
    def __init__(self, hardware_config_path: str, sequence_config_path: str, f3c_to_gui_queue: queue.Queue, command_queue: queue.Queue,
                 ack_queue: queue.Queue, system_state: State = State.IDLE):
        # commented out attributes are moved to thread safe access block
        self.sequence_config_path = sequence_config_path
        self.hardware_config_path = hardware_config_path
        self.f3c_to_gui_queue = f3c_to_gui_queue
        self.transitions = self._build_transitions()
        self.sequences = self._build_sequences(sequence_config_path)
        self.actuator_list = self._build_actuator_list(hardware_config_path)
        # self.state = State.IDLE
        self.fill_executed = False
        self.fire_executed = False
        # self.step_status = StepStatus.READY
        # self.current_step = None
        # self.step_list = deque(maxlen=100)
        self.single_valve_actuation = "single valve actuation"

        # elyse added this
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._command_queue = command_queue
        self._ack_queue = ack_queue

        # elyse moved attributes to thread safe access w locks
        with self._lock:
            self.state: State.IDLE
            self.step_status: StepStatus = StepStatus.READY
            self.active_sequence: str = "idle"
            self.current_step_index: int | None = None
            self.current_step: None
            self.step_list = deque(maxlen=100)
            self.history: list[dict] = []
            self.waiting_manual: dict | None = None

    # elyse added this, for gui simulation mode, reset button will reset sequence and state
    def reset_sequences(self):
        with self._lock:
            self.state = State.IDLE
            self.step_status = StepStatus.READY
            self.active_sequence = "idle"
            self.current_step_index = None
            self.current_step = None
            try:
                self.step_list.clear()
            except Exception:
                pass
            self.waiting_manual = None
            self.history.clear()

    def get_state(self) -> State:
        return self.state

    def get_step_status(self) -> StepStatus:
        return self.step_status

    def get_current_step(self) -> dict[str, Any] | None:
        return self.current_step

    def shutdown(self) -> None:
        self._stop_event.set()
        try:
            self._command_queue.put(None, timeout=0.1)
        except Exception:
            pass

    # gui calls this to get a snapshot of the current system state for display and decision-making purposes
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self.state
            valves: dict[str, str] = {}
            for v in self.actuators.values():
                try:
                    key = str(getattr(v, "valve_id", "")).upper()
                    val = getattr(getattr(v, "state", None), "value", None)
                    if key and isinstance(val, str):
                        valves[key] = val
                except Exception:
                    pass
            return {
                "system_state": str(getattr(state, "name", "IDLE")).upper(),
                "active_sequence": str(self.active_sequence),
                "current_step_index": self.current_step_index,
                "step_status": str(getattr(self.step_status, "value", "ready")),
                "current_step": dict(self.current_step) if isinstance(self.current_step, dict) else None,
                "history": list(self.history),
                "waiting_manual": dict(self.waiting_manual) if self.waiting_manual else None,
                "valves": valves,
            }


    # placeholder for single valve actuation (keep this method name so gui can call)
    def _set_valve_from_gui(self):
        return

    # 
    def get_sequence_definitions_for_gui(self) -> list[dict[str, Any]]:
        ordered = ["idle", "fill", "fire"]
        out: list[dict[str, Any]] = []
        for key in ordered:
            seq = self.sequences.get(key)
            name = key.upper()
            steps_raw: list[Any] = []
            if isinstance(seq, dict):
                name_field = seq.get("name")
                if isinstance(name_field, str) and name_field:
                    name = name_field.upper()
                steps_field = seq.get("steps")
                if isinstance(steps_field, list):
                    steps_raw = steps_field

            steps: list[dict[str, Any]] = []
            for i, step in enumerate(steps_raw):
                if not isinstance(step, dict):
                    continue
                valve = step.get("valve")
                action = step.get("action")
                if not isinstance(valve, str):
                    valve = str(valve) if valve is not None else ""
                if not isinstance(action, str):
                    action = str(action) if action is not None else ""
                time_delay = step.get("time_delay", 0.0)
                try:
                    time_delay_s = float(time_delay or 0.0)
                except Exception:
                    time_delay_s = 0.0
                steps.append(
                    {
                        "index": int(i),
                        "valve": valve.upper(),
                        "action": action.lower(),
                        "time_delay_s": time_delay_s,
                        "user_input": bool(step.get("user_input", False)),
                        "condition_valve": (str(step.get("condition_valve")).upper() if step.get("condition_valve") else None),
                        "condition_state": (str(step.get("condition_state")) if step.get("condition_state") is not None else None),
                        "system_state": (str(step.get("system_state")).upper() if step.get("system_state") is not None else name),
                    }
                )
            out.append({"name": name, "key": key, "steps": steps})
        return out

    def _loop(self):
        while not self._stop_event.is_set():
            # change implementation to 
            gui_input = self.gui_to_f3c_queue.get() # waits for an item in the queue with an interrupt
            if gui_input is None:
                break
            if gui_input in [s.value for s in State]:
                self._execute_action(gui_input)
            else:
                pass 

    def _record_history(self, *, sequence: str, step_index: int, status: str,
        valve: str | None = None, action: str | None = None):
        with self._lock:
            rec: dict[str, Any] = {
                "sequence": sequence,
                "step_index": int(step_index),
                "status": str(status),
                "t_wall": time.time(),
            }
            if valve:
                rec["valve"] = str(valve)
            if action:
                rec["action"] = str(action)
            self.history.append(rec)

    def _execute_action(self, action: str, valve_id=None, valve_state=None):
        """
        Method for executing any type of action.
        Args:
            action (str): action to execute, comes from GUI
            valve_id (int): valve id of the valve for single valve actuation, None by default
            valve_state (ValveState): valve state of the valve for single valve actuation, None by default
        """

        # if desired action is a valid, defined transition from current state
        with self._lock:
            current_state = self.state
        transition_key = (current_state, TransitionAction(action))
        if transition_key in self.transitions:

            # if trying to fill or fire
            if action in (State.FILL.value, State.FIRE.value):

                # update system state to reflect command
                sequence_state = self.transitions.get(transition_key)
                self.state = sequence_state

                # loop through each step in sequence
                current_sequence = self.sequences.get(action)
                for idx, step in enumerate(current_sequence.get("steps")):

                    # check state at each step to catch aborts
                    # TO DO: change this to thread interrupt or maybe keep but do both
                    with self._lock:
                        current_state = self.state
                    if current_state == sequence_state:
                        valve_id = step.get("valve_id")
                        current_valve = self.actuator_list.get(valve_id)
                        self.step_status = StepStatus.EXECUTING
                        self.current_step_index = int(idx)
                        self.current_step = {
                            "index": int(idx),
                            "valve": valve_id,
                            # "action": action_s,
                            "time_delay": step.get("time_delay", 0.0),
                            "user_input": bool(step.get("user_input", False)),
                            "condition_valve": step.get("condition_valve"),
                            "condition_state": step.get("condition_state"),
                            "system_state": self.state.value,
                        }
                        self._record_history(sequence=sequence_state, step_index=idx, status="READY", valve=valve_id, action=action)

                        # if the valve for this step is a throttle valve
                        if isinstance(current_valve, ThrottleValve):
                            # TO DO: throttling implementation
                            # TO DO: need to have something that limits what OF you can have based on angles provided by
                            # throttle controller, absolute max of 1.2
                            pass
                        else:
                            valve_goal_state = ValveState(step.get("action"))

                            # valve actuation command
                            current_valve.set_state(valve_goal_state)

                            # wait for delay specified in step (can be 0.0)
                            time.sleep(step.get("time_delay"))
                            if step.get("user_input"):
                                self.step_status = StepStatus.WAITING_USER
                                self.f3c_to_gui_queue.put(self.step_status)
                                self.gui_to_f3c_queue.get()

                            self.step_list.append(self.current_step)
                            self.step_status = StepStatus.READY
                            
            elif action == State.ABORT.value:
                # TO DO: implement end thread aborting functionality
                pass
            elif action == self.single_valve_actuation:
                if valve_id is None:
                    # TO DO: send error saying no valve_id was provided
                    pass
                elif valve_state is None:
                    # TO DO: send error saying no valve state was provided
                    pass
                else:
                    current_valve = self.actuator_list.get(valve_id)
                    current_valve.set_state(valve_state)
        else:
            # TO DO: send message to gui saying request was invalid based on state
            pass

    def shutdown(self):
        self.gui_to_f3c_queue.put(None)

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