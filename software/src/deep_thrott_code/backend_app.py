from __future__ import annotations

"""Backend Flask app factory + DAQ runtime helpers.

This module builds the backend process that the GUI connects to.

High-level architecture:
- DAQ side produces samples and pushes them onto `gui_queue`.
- A Socket.IO loop (registered in `deep_thrott_code/gui/sockets.py`) drains
	`gui_queue` and emits `daq_packet` to the browser.
- The sequencing runtime exposes a separate snapshot function; the Socket.IO
	loop emits that as `system_packet` so DAQ telemetry never overwrites GUI state.

Queues used by the backend:
- `gui_queue`: DAQ samples destined for the GUI.
- `command_queue`: high-level GUI commands intended for the sequencing runtime
	(e.g. "fill", "fire").
- `control_queue`: GUI control commands for this backend process
	(start/stop log, toggle simulation, etc.).

Note on Controller integration:
- The F3C Controller consumes commands and manual-step acknowledgements on
	separate queues (`command_queue` and `gui_to_f3_queue`).
"""

# Standard library imports
import argparse
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

# Web framework import (the GUI talks to this backend over Socket.IO)
from flask import Flask


@dataclass(frozen=True)
class BackendConfig:
	# CLI/config values for starting the backend process.
	# (These are read once at process startup.)
	host: str
	port: int
	debug: bool
	autostart: bool
	simulation: bool


def parse_args() -> BackendConfig:
	"""Parse CLI flags for running the backend as a standalone process."""

	# We keep argument parsing here so `deep_thrott_code.main` can use it,
	# and so `python -m deep_thrott_code.backend_app` could also use it.
	parser = argparse.ArgumentParser(description="Deep Thrott Code backend (DAQ + Socket.IO)")
	# Bind host for the web server.
	parser.add_argument("--host", default="0.0.0.0", help="Bind host (0.0.0.0 to listen on LAN)")
	parser.add_argument(
		"--port",
		type=int,
		# 6000 is blocked by some browsers as an unsafe port; use 6001.
		default=6001,
		help="Bind port for backend Socket.IO (6000 is browser-unsafe; default 6001)",
	)
	# Flask debug mode (auto-reload is disabled elsewhere).
	parser.add_argument("--debug", action="store_true", help="Enable Flask debug")
	# Convenience: start DAQ logging immediately after launching the backend.
	parser.add_argument("--autostart", action="store_true", help="Start logging immediately")
	parser.add_argument(
		"--simulation",
		action="store_true",
		# Default is False, but the GUI can still toggle simulation at runtime.
		help="Default to Simulation Mode ON at startup (still changeable via GUI)",
	)
	# Parse the args and normalize types.
	args = parser.parse_args()
	return BackendConfig(
		host=str(args.host),
		port=int(args.port),
		debug=bool(args.debug),
		autostart=bool(args.autostart),
		simulation=bool(args.simulation),
	)


def create_backend_app(
	*,
	gui_queue: queue.Queue,
	command_queue: queue.Queue,
	control_queue: queue.Queue,
	f3_to_gui_queue: queue.Queue | None = None,
	gui_to_f3_queue: queue.Queue | None = None,
	get_system_snapshot: Callable[[], dict] | None = None,
	sequence_defs: list[dict] | None = None,
) -> Flask:
	"""Create the Flask backend and register Socket.IO handlers.

	`register_socket_handlers()` starts the 10Hz emit loop thread that:
	- drains `gui_queue` and emits `daq_packet`
	- calls `get_system_snapshot` and emits `system_packet`
	- forwards manual-step messages (if sequencing runtime queues are configured)
	"""

	# IMPORTANT: these imports are intentionally inside the function.
	# That lets parts of the codebase import `backend_app.py` even in environments
	# that don't have Flask-SocketIO installed (e.g., some CI or tooling).
	# Local imports to keep this module importable in more environments.
	from deep_thrott_code.gui.extensions import socketio  # noqa: PLC0415
	from deep_thrott_code.gui.sockets import register_socket_handlers  # noqa: PLC0415

	# Create the Flask WSGI app object.
	app = Flask(__name__)
	# Secret key is required by Flask extensions; "dev" is fine for local work.
	app.config["SECRET_KEY"] = "dev"

	# Attach Socket.IO to the Flask app.
	socketio.init_app(app)
	# Register event handlers + start the periodic emit loop (10 Hz).
	# This is where the GUI actually gets its live telemetry.
	register_socket_handlers(
		socketio,
		app,
		# DAQ samples destined for the browser.
		gui_queue=gui_queue,
		# Sequencer commands (fill/fire/etc.).
		command_queue=command_queue,
		# Backend control commands (start/stop/toggle sim).
		control_queue=control_queue,
		# Optional: messages from the sequencer runtime -> GUI.
		f3_to_gui_queue=f3_to_gui_queue,
		# Optional: manual-step acknowledgements GUI -> sequencer.
		gui_to_f3_queue=gui_to_f3_queue,
		# Optional: sequencer snapshot function; emitted separately from DAQ.
		get_system_snapshot=get_system_snapshot,
		# Optional: sequence definitions for the GUI.
		sequence_defs=sequence_defs,
	)
	return app


def drain_queue(q: queue.Queue) -> None:
	"""Best-effort queue drain used to drop stale samples on restarts."""

	# We drain by repeatedly calling get_nowait() until it raises.
	# This is used when restarting logging to ensure the GUI doesn't show old data.
	while True:
		try:
			q.get_nowait()
		except Exception:
			# Queue is empty (or otherwise not drainable).
			break
		else:
			# Some Queue implementations track unfinished tasks; ignore failures.
			try:
				q.task_done()
			except Exception:
				pass


def emit_system(text: str) -> None:
	"""Emit a one-line system message to the GUI (best-effort)."""

	# This is intentionally "best-effort": if Socket.IO isn't ready
	# or the GUI isn't connected yet, we just drop the message.
	# Local import so this module stays importable without Flask-SocketIO.
	from deep_thrott_code.gui.extensions import socketio  # noqa: PLC0415

	try:
		# The frontend listens for this event and prints it to the System Messages panel.
		socketio.emit("system_message", {"text": text})
	except Exception:
		pass


class DaqRuntime:
	"""Owns DAQ producer/consumer threads and related state."""

	def __init__(
		self,
		*,
		gui_queue: queue.Queue,
		sample_queue: queue.Queue,
		emit_system_fn: Callable[[str], None],
		drain_queue_fn: Callable[[queue.Queue], None],
		pin_thread_to_cpu: Callable[[int], None],
		producer_cpu: int,
		consumer_cpu: int,
		log_path: str = "daq_backend_log.csv",
	) -> None:
		# Queues shared with the rest of the backend.
		# - _sample_queue is producer -> consumer (internal)
		# - _gui_queue is consumer -> GUI emit loop
		self._gui_queue = gui_queue
		self._sample_queue = sample_queue

		# Dependency-injected helpers so this class is testable and platform-flexible.
		self._emit_system = emit_system_fn
		self._drain_queue = drain_queue_fn
		self._pin_thread_to_cpu = pin_thread_to_cpu

		# CPU affinity targets for Raspberry Pi (see deep_thrott_code/main.py notes).
		self._producer_cpu = int(producer_cpu)
		self._consumer_cpu = int(consumer_cpu)

		# Output CSV path for the DAQ logger.
		self._log_path = str(log_path)

		# Lock protects start/stop + the runtime fields below.
		self._lock = threading.Lock()
		# True if the DAQ threads are currently running.
		self._running = False
		# Stop signal shared by producer + consumer.
		self._stop_event: threading.Event | None = None
		# Background threads.
		self._producer_thread: threading.Thread | None = None
		self._consumer_thread: threading.Thread | None = None
		# Runtime-owned resources.
		self._logger = None
		self._state_store = None

	def is_running(self) -> bool:
		# Query-only method; returns a snapshot under the lock.
		with self._lock:
			return bool(self._running)

	def start(self, simulation: bool) -> None:
		"""Start DAQ threads and begin emitting samples to `gui_queue`.

		The producer reads sensors (or sim sources) into `sample_queue`.
		The consumer converts samples into GUI-friendly updates and logs to CSV.
		"""

		# Imports are inside the method so the module can be imported in environments
		# that don't have all dependencies installed (or don't need the DAQ).
		from deep_thrott_code.daq.services.loop import consumer_loop, producer_loop  # noqa: PLC0415
		from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
		from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
		from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415

		# Guard against double-start.
		with self._lock:
			if self._running:
				self._emit_system("Log already running.")
				return

		# Build the sensors list.
		# - simulation=True: fake data
		# - simulation=False: real hardware (ADC)
		try:
			sensors = build_sensors(simulation=bool(simulation))
		except Exception as e:
			# Send the error to the GUI and bail.
			self._emit_system(str(e))
			return

		# Build name -> sensor object lookup used by the consumer loop.
		sensor_map = build_sensor_map(sensors)
		# Stop event is set when we want threads to exit.
		stop_event = threading.Event()
		# StateStore holds "latest value" per sensor (used for GUI snapshot-style telemetry).
		state_store = StateStore()
		# CsvLogger writes one row per converted sample.
		logger = CsvLogger(self._log_path, flush_every=25, fsync_every_flush=False)

		# Drop any stale queued items from a prior run.
		self._drain_queue(self._sample_queue)
		self._drain_queue(self._gui_queue)

		def producer_entrypoint() -> None:
			# Producer thread:
			# - reads each sensor (raw)
			# - enqueues RawSample(s) into _sample_queue
			# CPU pinning is optional; on Windows this may no-op depending on impl.
			self._pin_thread_to_cpu(self._producer_cpu)
			# 50 Hz is the current fixed rate for the GUI-backed DAQ runtime.
			producer_loop(sensors, self._sample_queue, stop_event, 50.0)

		def consumer_entrypoint() -> None:
			# Consumer thread:
			# - drains _sample_queue
			# - converts raw samples -> engineering units
			# - updates StateStore
			# - enqueues converted Sample(s) to gui_queue
			# - writes to CSV
			# The consumer is the only place that touches StateStore + logger.
			self._pin_thread_to_cpu(self._consumer_cpu)
			consumer_loop(self._sample_queue, self._gui_queue, state_store, logger, stop_event, sensor_map)

		# Create daemon threads so the process can exit even if something forgets to stop.
		producer_thread = threading.Thread(target=producer_entrypoint, daemon=True, name="producer")
		consumer_thread = threading.Thread(target=consumer_entrypoint, daemon=True, name="consumer")
		# Start both loops.
		producer_thread.start()
		consumer_thread.start()

		# Publish runtime state under the lock.
		with self._lock:
			self._running = True
			self._stop_event = stop_event
			self._producer_thread = producer_thread
			self._consumer_thread = consumer_thread
			self._logger = logger
			self._state_store = state_store

		# Tell the GUI what just happened.
		self._emit_system(f"Backend log started ({'SIM' if simulation else 'ADC'} mode).")

	def stop(self) -> None:
		"""Stop DAQ threads and close the logger (best-effort)."""

		# Copy out references under the lock so we can do blocking joins
		# without holding the lock (prevents deadlocks / UI stalls).
		with self._lock:
			if not self._running:
				self._emit_system("No log running.")
				return
			# Snapshot the runtime objects.
			stop_event = self._stop_event
			producer_thread = self._producer_thread
			consumer_thread = self._consumer_thread
			logger = self._logger
			# Clear state first so re-entrancy (or double-stop) is safe.
			self._running = False
			self._stop_event = None
			self._producer_thread = None
			self._consumer_thread = None
			self._logger = None
			self._state_store = None

		# Signal both threads to stop.
		if stop_event is not None:
			stop_event.set()
		# Join threads briefly to allow clean shutdown.
		if producer_thread is not None:
			producer_thread.join(timeout=1.0)
		if consumer_thread is not None:
			consumer_thread.join(timeout=1.0)

		# Close the CSV logger.
		try:
			if logger is not None:
				logger.close()
		except Exception:
			pass

		# Drop any queued items so the next start begins from a clean slate.
		self._drain_queue(self._sample_queue)
		self._drain_queue(self._gui_queue)
		# Notify the GUI.
		self._emit_system("Backend log stopped.")




    # def _run_sequence(self, sequence_key: str, seq_state: State) -> None:
    #     seq = self.sequences.get(sequence_key)
    #     steps: list[Any] = []
    #     if isinstance(seq, dict):
    #         maybe_steps = seq.get("steps")
    #         if isinstance(maybe_steps, list):
    #             steps = maybe_steps

    #     with self._lock:
    #         self.state = seq_state
    #         self.active_sequence = sequence_key
    #         self.current_step_index = None
    #         self.step_status = StepStatus.READY
    #         self.waiting_manual = None

    #     for idx, step in enumerate(steps):
    #         if not isinstance(step, dict):
    #             continue
    #         valve = step.get("valve")
    #         action = step.get("action")
    #         valve_s = valve if isinstance(valve, str) else str(valve or "")
    #         action_s = action if isinstance(action, str) else str(action or "")

    #         with self._lock:
    #             self.current_step_index = int(idx)
    #             self.step_status = StepStatus.EXECUTING
    #             sys_state = step.get("system_state")
    #             if isinstance(sys_state, str) and sys_state:
    #                 try:
    #                     self.state = State(sys_state.lower())
    #                 except Exception:
    #                     self.state = seq_state
    #             else:
    #                 self.state = seq_state
    #             self.current_step = {
    #                 "index": int(idx),
    #                 "valve": valve_s,
    #                 "action": action_s,
    #                 "time_delay": step.get("time_delay", 0.0),
    #                 "user_input": bool(step.get("user_input", False)),
    #                 "condition_valve": step.get("condition_valve"),
    #                 "condition_state": step.get("condition_state"),
    #                 "system_state": sys_state,
    #             }

    #         self._record_history(sequence=sequence_key, step_index=idx, status="READY", valve=valve_s, action=action_s)
    #         try:
    #             act = self.actuators.get(valve_s.lower())
    #         except Exception:
    #             act = None

    #         if act is not None:
    #             try:
    #                 act.set_state(ValveState(action_s.lower()))
    #             except Exception:
    #                 pass

    #         if bool(step.get("user_input", False)):
    #             with self._lock:
    #                 self.step_status = StepStatus.WAITING_USER
    #                 self.waiting_manual = {"sequence": sequence_key, "step_index": int(idx)}
    #             self._record_history(sequence=sequence_key, step_index=idx, status="WAITING_USER", valve=valve_s, action=action_s)
    #             try:
    #                 self._f3c_to_gui_queue.put(
    #                     {
    #                         "type": "manual_step_required",
    #                         "sequence": sequence_key,
    #                         "step_index": int(idx),
    #                         "message": "Manual step required. Perform the required checks, then click Execute.",
    #                     },
    #                     timeout=0.1,
    #                 )
    #             except Exception:
    #                 pass

    #             # Block until matching ack arrives.
    #             while True:
    #                 ack = self._ack_queue.get()
    #                 try:
    #                     if ack is None:
    #                         break
    #                     if isinstance(ack, dict) and ack.get("type") == "reset_sequences":
    #                         self.reset_sequences()
    #                         return
    #                     if isinstance(ack, dict) and ack.get("type") == "manual_step_execute":
    #                         seq = ack.get("sequence")
    #                         step_index = ack.get("step_index")
    #                         try:
    #                             ack_idx = int(step_index)
    #                         except Exception:
    #                             ack_idx = None
    #                         if seq == sequence_key and ack_idx == int(idx):
    #                             break
    #                 finally:
    #                     try:
    #                         self._ack_queue.task_done()
    #                     except Exception:
    #                         pass
    #             with self._lock:
    #                 self.waiting_manual = None
    #                 self.step_status = StepStatus.EXECUTING

    #         self._record_history(sequence=sequence_key, step_index=idx, status="EXECUTING", valve=valve_s, action=action_s)

    #         time_delay = step.get("time_delay", 0.0)
    #         # try:
    #         #     time_delay_s = float(time_delay or 0.0)
    #         # except Exception:
    #         #     time_delay_s = 0.0
    #         # if time_delay_s > 0:
    #         #     time.sleep(time_delay_s)

    #         with self._lock:
    #             try:
    #                 self.step_list.append(dict(self.current_step) if isinstance(self.current_step, dict) else {"index": int(idx)})
    #             except Exception:
    #                 pass
    #         self._record_history(sequence=sequence_key, step_index=idx, status="COMPLETED", valve=valve_s, action=action_s)

    #     with self._lock:
    #         self.current_step_index = None
    #         self.current_step = None
    #         self.active_sequence = "idle"
    #         self.state = State.IDLE
    #         self.step_status = StepStatus.READY
    #         self.waiting_manual = None

    # @staticmethod
    # def _build_transitions() -> dict[tuple[State, TransitionAction], State]:
    #     """Minimal legacy transition table.

    #     This is used to preserve the old `_execute_action` gating behavior.
    #     """

    #     return {
    #         (State.IDLE, TransitionAction.FILL): State.FILL,
    #         (State.IDLE, TransitionAction.FIRE): State.FIRE,
    #         (State.FILL, TransitionAction.END): State.IDLE,
    #         (State.FIRE, TransitionAction.END): State.IDLE,
    #         (State.THROTTLE, TransitionAction.END): State.IDLE,
    #         (State.FILL, TransitionAction.ABORT): State.ABORT,
    #         (State.FIRE, TransitionAction.ABORT): State.ABORT,
    #         (State.THROTTLE, TransitionAction.ABORT): State.ABORT,
    #     }

