from __future__ import annotations
from collections import deque
import queue
import threading
import time
from enum import Enum
from typing import Any
import yaml
from valve import Valve, ValveState, ThrottleValve
import os
import serial

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
    FILL = "fill"                # when a fill sequence starts
    FIRE = "fire"                # when a fire sequences starts
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
    def __init__(
        self,
        hardware_config_file: str | None = None,
        sequence_config_file: str | None = None,
        command_queue: queue.Queue | None = None,
        ack_queue: queue.Queue | None = None,
        *,
        # New-style kwargs used by deep_thrott_code.main
        hardware_config_path: str | None = None,
        sequence_config_path: str | None = None,
        f3c_to_gui_queue: queue.Queue | None = None,
        system_state: State = State.IDLE,
    ):
        # commented out attributes are moved to thread safe access block
        if command_queue is None or ack_queue is None:
            raise TypeError("command_queue and ack_queue are required")

        self._f3c_to_gui_queue = f3c_to_gui_queue

        # getting config file directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_dir = os.path.join(base_dir, "config")

        # defining where the config files are
        if sequence_config_path is not None:
            self.sequence_config_file = str(sequence_config_path)
        else:
            self.sequence_config_file = os.path.join(config_dir, str(sequence_config_file))

        if hardware_config_path is not None:
            self.hardware_config_file = str(hardware_config_path)
        else:
            self.hardware_config_file = os.path.join(config_dir, str(hardware_config_file))

        # building stuff from config files
        print(f"Building transitions...")
        self.transitions = self._build_transitions()
        print(f"Building sequences from {self.sequence_config_file}...")
        self.sequences = self._build_sequences(self.sequence_config_file)
        print(f"Building actuator list from {self.hardware_config_file}...")
        self.actuator_list = self._build_actuator_list(self.hardware_config_file)
        print(f"Initialization complete.")

        self.fill_executed = False
        self.fire_executed = False

        self.single_valve_actuation = "single valve actuation"
        self.pulse = "pulse"

        # elyse added this
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._command_queue = command_queue
        self._ack_queue = ack_queue

        # elyse moved attributes to thread safe access w locks
        with self._lock:
            self.state: State = system_state
            self.step_status: StepStatus = StepStatus.READY
            self.active_sequence: str = "idle"
            self.current_step_index: int | None = None
            self.current_step = None
            self.step_list = deque(maxlen=100)
            self.history: list[dict] = []
            self.waiting_manual: dict | None = None
            # necessary to lock serial?
            self.ser = serial.Serial("/dev/ttyACM0", baudrate=115200, timeout=0.1)

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
            for v in self.actuator_list.values():
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
        ordered = ["idle", "fire"]
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
                valve_id = step.get("valve_id")
                action = step.get("action")
                if not isinstance(valve_id, str):
                    valve_id = str(valve_id) if valve_id is not None else ""
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
                        "valve_id": valve_id.upper(),
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
    
    # main loop that is checking the command queue for gui commands always
    def start(self):
        print("Controller.start() loop entered")
        while not self._stop_event.is_set():
            print("Controller.start() waiting for command...")
            gui_input = self._command_queue.get() # waits for an item in the queue with an interrupt
            print(f"Queue item received: {gui_input}")

            # shutdown functionality
            if gui_input is None:
                break
            else:
                
                # unpacking gui input dict
                cmd_type = gui_input.get("type")
                
                # single valve actuation
                if cmd_type == "set_valve":
                    print("Single valve actuation branch in start() reached")
                    valve_id = gui_input.get("valve_id")
                    state = gui_input.get("state") or gui_input.get("valve_state")
                    if isinstance(valve_id, str) and isinstance(state, str):
                        valve_key = valve_id.strip().lower()
                        st = state.strip().lower()
                        if st == "open":
                            valve_goal_state = ValveState.OPEN
                        else:
                            valve_goal_state = ValveState.CLOSED
                        self._execute_action(self.single_valve_actuation, valve_key, valve_goal_state)
                    self._command_queue.task_done()
                    continue
                    
                elif cmd_type == "pulse_valve":
                    valve_id = gui_input.get("valve_id")
                    if isinstance(valve_id, str):
                        valve_key = valve_id.strip().lower()
                        self._execute_action(self.pulse, valve_key)
                # reset sequences for gui test
                elif cmd_type == "reset_sequences":
                    self.reset_sequences()
                    self._command_queue.task_done()
                    continue
                
                # fill and fire sequences
                elif cmd_type in (State.FILL.value, State.FIRE.value):
                    self._execute_action(cmd_type)
                    self._command_queue.task_done()
            try:
                self._command_queue.task_done()
            except Exception:
                pass

    # Compatibility shim: backend expects loop_forever()
    def loop_forever(self) -> None:
        self.start()

    def _record_history(self, *, sequence: str, step_index: int, status: str,
        valve_id: str | None = None, action: str | None = None, dt: float | None = None):
        with self._lock:
            rec: dict[str, Any] = {
                "sequence": sequence,
                "step_index": int(step_index),
                "status": str(status),
                "t_wall": time.time(),
            }
            if valve_id:
                rec["valve_id"] = str(valve_id)
            if action:
                rec["action"] = str(action)
            if dt:
                rec["dt"] = float(dt)
            self.history.append(rec)

    def _execute_action(self, action: str, valve_id: str | None =None, valve_state=None, dt: float | None = None):
        """
        Method for executing any type of action.
        Args:
            action (str): action to execute, comes from GUI
            valve_id (int): valve id of the valve for single valve actuation, None by default
            valve_state (ValveState): valve state of the valve for single valve actuation, None by default
        """
        
        #if trying to fill or fire
        if action in (State.FILL.value, State.FIRE.value):
            threading.Thread(target=self._execute_sequence, args=(action,)).start()

        # if performing single valve actuation or pulse
        if action in (self.single_valve_actuation, self.pulse):
            current_valve = self.actuator_list.get(valve_id)
            if action == self.single_valve_actuation:
                threading.Thread(target=self._execute_single_valve_actuation, args=(current_valve, valve_state)).start()
            else:
                threading.Thread(target=self._execute_pulse, args=(current_valve, dt)).start()
                            
    
    def _execute_sequence(self, sequence_name: str):
        # if desired action is a valid, defined transition from current state
        with self._lock:
            current_state = self.state
        transition_key = (current_state, TransitionAction(sequence_name))
        if transition_key in self.transitions:

            # update system state to reflect command
            sequence_state = self.transitions.get(transition_key)
            with self._lock:
                self.state = sequence_state

            # loop through each step in sequence
            # TO DO: add checks that see if next step is valid based on condition valve and state
            current_sequence = self.sequences.get(sequence_name)
            for idx, step in enumerate(current_sequence.get("steps")):

                # check state at each step to catch aborts
                # TO DO: change this to thread interrupt or maybe keep but do both
                with self._lock:
                    current_state = self.state
                if current_state == sequence_state:
                    
                    # get valve and individual valve action at this step
                    valve_id = step.get("valve_id")
                    action_seq = step.get("action")
                    valve_key = str(valve_id).lower()
                    current_valve = self.actuator_list.get(valve_key)
                    
                    # update current step information
                    with self._lock:
                        self.step_status = StepStatus.EXECUTING
                        self.current_step_index = int(idx)
                        self.current_step = {
                            "index": int(idx),
                            "valve_id": valve_id,
                            "action": action_seq,
                            "time_delay": step.get("time_delay", 0.0),
                            "user_input": bool(step.get("user_input", False)),
                            "condition_valve": step.get("condition_valve"),
                            "condition_state": step.get("condition_state"),
                            "system_state": self.state.value,
                        }
                    
                    # record this step
                    self._record_history(sequence=str(sequence_state.value), step_index=idx, status="READY",
                                         valve_id=str(valve_id), action=action_seq)

                    # if the valve for this step is a throttle valve
                    if isinstance(current_valve, ThrottleValve):
                        # TO DO: throttling implementation
                        # TO DO: need to have something that limits what OF you can have based on angles provided by
                        # throttle controller, absolute max of 1.2
                        pass
                    
                    # if the valve for this step is an on/off valve
                    else:
                        if current_valve is None:
                            # TO DO: record error history
                            continue

                        # gets valve action
                        act = str(step.get("action") or "").lower()
                        if act == "open":
                            valve_goal_state = ValveState.OPEN
                        elif act == "closed":
                            valve_goal_state = ValveState.CLOSED
                        else:
                            # Unknown action, skip or default to CLOSED
                            continue
                            
                        # actuates valve if current valve state is different from goal state
                        if current_valve.get_state() != valve_goal_state:
                            current_valve.set_state(valve_goal_state)
                        # if not, stop and move on to next step
                        else:
                            with self._lock:
                                self.step_status = StepStatus.READY
                            continue

                        # wait for delay specified in step (can be 0.0)
                        time.sleep(step.get("time_delay", 0.0))
                        if bool(step.get("user_input")):
                            with self._lock:
                                self.step_status = StepStatus.WAITING_USER
                            self.waiting_manual = {"sequence": str(sequence_state.value), "step_index": int(idx)}
                            self._record_history(sequence=str(sequence_state.value), step_index=idx, status="WAITING_USER",
                                                 valve_id=str(valve_id), action=action_seq)

                            # send message to gui that manual step is required with step details
                            if self._f3c_to_gui_queue is not None:
                                self._f3c_to_gui_queue.put(
                                    {
                                        "type": "manual_step_required",
                                        "sequence": str(sequence_state.value),
                                        "step_index": int(idx),
                                        "message": "Manual step required. Perform the required checks, then click Execute.",
                                    },
                                    timeout=0.1,
                                )

                            # Block until matching acknowledgement arrives
                            while True:
                                ack = self._ack_queue.get()
                                try:
                                    if isinstance(ack, dict) and ack.get("type") == "reset_sequences":
                                        self.reset_sequences()
                                        return

                                    if isinstance(ack, dict) and ack.get("type") == "manual_step_execute":
                                        seq = ack.get("sequence")
                                        step_index = ack.get("step_index")
                                        ack_idx = int(step_index)
                                        # what happens if this isn't true?
                                        if seq == str(sequence_state.value) and ack_idx == int(idx):
                                            break
                                finally:
                                    self._ack_queue.task_done()
                        with self._lock:
                            self.step_list.append(self.current_step)
                            self.step_status = StepStatus.READY
        else:
            # TO DO: send to gui "invalid state transition"
            pass

    def _execute_single_valve_actuation(self, valve: Valve, valve_state: ValveState):
        valve.set_state(valve_state)
        # TO DO: log valve actuation

    def _execute_pulse(self, valve: Valve, dt: float):
        valve.pulse_valve(dt)
        # TO DO: log valve actuation
    
    @staticmethod
    def _build_transitions() -> dict[tuple[State, TransitionAction], State]:
        """
        Defines the allowed transitions between states. Provided the current state and the action that will be executed, 
        the dict provides what next state the system should enter.
        
        Key: (current state, transition action)
        Value: next state
        """""
        return {
            (State.IDLE, TransitionAction.FIRE): State.FIRE,
            (State.IDLE, TransitionAction.ABORT): State.ABORT,
            (State.FIRE, TransitionAction.END): State.IDLE,
            (State.FIRE, TransitionAction.ABORT): State.ABORT,
            (State.FIRE, TransitionAction.AUTO): State.THROTTLE,
            (State.THROTTLE, TransitionAction.AUTO): State.FIRE,
            (State.ABORT, TransitionAction.EXIT_SAFE): State.IDLE,
        }


    @staticmethod
    def _build_sequences(sequence_config_path: str):
        """
        Builds the fire sequence based on the sequences config file.

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
            actuator_info_list = (hardware_config.get("actuators") or {}).get("valves") or {}
            actuator_list: dict[str, Any] = {}
            for valve_id, actuator_info in actuator_info_list.items():
                if actuator_info.get("mode") == "on_off":
                    actuator_list[str(valve_id)] = Valve(str(valve_id), int(actuator_info.get("pin")), bool(actuator_info.get("active_high")))
                else:
                    actuator_list[str(valve_id)] = ThrottleValve(str(valve_id), int(actuator_info.get("pin")), bool(actuator_info.get("active_high")))
        return actuator_list
