"""Socket.IO handlers and GUI update loop.

This module is the main bridge between:
- The backend's internal Python queues (DAQ + controller)
- The browser GUI, connected via Flask-SocketIO

There are two directions of flow:

1) Backend -> GUI (push telemetry/state)
	 - DAQ / runtime code pushes samples onto `gui_queue`.
	 - A background thread in this module runs at ~10 Hz and:
			 - drains `gui_queue` (non-blocking)
			 - keeps the latest value per sensor
			 - emits a consolidated `daq_packet` to the browser
	 - Separately, it emits a `system_packet` produced by `get_system_snapshot`
		 (sequencer/controller state, which we keep separate from DAQ telemetry).

2) GUI -> Backend (send commands)
	 - The browser emits events like `gui_command` and `manual_step_execute`.
	 - The handlers validate payloads, then enqueue work onto:
			 - `command_queue` (sequencer/controller commands)
			 - `control_queue` (backend runtime controls: start/stop/toggle simulation)
			 - `gui_to_f3_queue` (manual-step acknowledgements back to sequencer)

Important note about `socketio.emit(...)`:
- In Flask-SocketIO, `socketio.emit` typically broadcasts to all clients
	unless you target a specific session/room.
- This project assumes a single GUI client most of the time.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable



def _sample_to_json(sample: Any) -> dict[str, Any]:  # noqa: ANN401
	"""Convert a sample object into a JSON-serializable dict.

	We use `getattr` so this works with both real sample classes and
	simpler mock objects in simulation/tests.
	"""

	return {
		"sensor_name": getattr(sample, "sensor_name", ""),
		"sensor_kind": getattr(sample, "sensor_kind", ""),
		"t_monotonic": float(getattr(sample, "t_monotonic", 0.0) or 0.0),
		"t_wall": float(getattr(sample, "t_wall", 0.0) or 0.0),
		"value": getattr(sample, "value", None),
		"units": getattr(sample, "units", ""),
		"status": getattr(sample, "status", ""),
		"message": getattr(sample, "message", ""),
	}


def register_socket_handlers(
	socketio: Any,
	app: Any,  # noqa: ANN401
	*,
	gui_queue: queue.Queue | None = None,
	command_queue: queue.Queue | None = None,
	control_queue: queue.Queue | None = None,
	f3_to_gui_queue: queue.Queue | None = None,
	gui_to_f3_queue: queue.Queue | None = None,
	get_system_snapshot: Any | None = None,  # callable -> dict
	sequence_defs: list[dict[str, Any]] | None = None,
	pin_thread_to_cpu: Callable[[int], None] | None = None,
	cpu: int | None = None,
) -> None:
	"""Register Socket.IO event handlers + start the 10Hz GUI loop.

	GUI loop (10Hz):
	- Drain gui_queue
	- Update latest states
	- Emit JSON packet with Flask-SocketIO

	Command path:
	- Receive GUI command
	- Validate
	- Emit reject or enqueue to command_queue and emit accept
	"""

	# latest_states is a "latest value" cache used to build `daq_packet`.
	# We keep this lock small/fast so the 10 Hz loop stays stable.
	latest_lock = threading.Lock()
	latest_states: dict[str, dict[str, Any]] = {}

	# Expose for other modules / debugging.
	app.config["LATEST_STATES"] = latest_states
	app.config["LATEST_LOCK"] = latest_lock
	app.config["GUI_QUEUE"] = gui_queue
	app.config["COMMAND_QUEUE"] = command_queue
	app.config["CONTROL_QUEUE"] = control_queue
	app.config["F3_TO_GUI_QUEUE"] = f3_to_gui_queue
	app.config["GUI_TO_F3_QUEUE"] = gui_to_f3_queue
	app.config["GET_SYSTEM_SNAPSHOT"] = get_system_snapshot
	app.config["SEQUENCE_DEFS"] = sequence_defs

	def drain_gui_queue() -> int:
		"""Drain `gui_queue` and update `latest_states`.

		We intentionally do *non-blocking* reads (`get_nowait`) so the GUI loop
		never stalls. If samples arrive faster than 10 Hz, older ones are dropped
		in favor of the most recent per sensor.
		"""

		if gui_queue is None:
			return 0

		drained = 0
		while True:
			try:
				sample = gui_queue.get_nowait()
			except queue.Empty:
				break
			else:
				gui_queue.task_done()
				drained += 1
				payload = _sample_to_json(sample)
				name = payload.get("sensor_name")
				if not name:
					continue
				with latest_lock:
					latest_states[str(name)] = payload
		return drained

	def build_packet() -> dict[str, Any]:
		"""Build the `daq_packet` sent to the GUI."""

		with latest_lock:
			states_copy = dict(latest_states)
		return {"t_wall": time.time(), "states": states_copy}

	def build_system_packet() -> dict[str, Any]:
		"""Build the `system_packet` sent to the GUI.

		This is kept separate from DAQ telemetry so controller/sequencer state
		updates don't overwrite sensor state (and vice versa) on the frontend.
		"""

		snap: dict[str, Any] = {}
		getter = app.config.get("GET_SYSTEM_SNAPSHOT")
		if callable(getter):
			try:
				maybe = getter()
				if isinstance(maybe, dict):
					snap = maybe
			except Exception:
				pass
		snap.setdefault("t_wall", time.time())
		return snap

	def drain_f3_to_gui_queue() -> None:
		"""Drain controller->GUI messages and emit relevant Socket.IO events."""

		q = app.config.get("F3_TO_GUI_QUEUE")
		if q is None:
			return
		while True:
			try:
				msg = q.get_nowait()
			except queue.Empty:
				break
			else:
				try:
					q.task_done()
				except Exception:
					pass
				if isinstance(msg, dict) and msg.get("type") == "manual_step_required":
					try:
						socketio.emit("manual_step_required", msg)
					except Exception:
						pass

	def gui_loop_thread() -> None:
		"""Main 10 Hz loop that pushes current backend state to the browser."""

		period_s = 0.1
		next_tick = time.perf_counter()
		while True:
			drain_gui_queue()
			drain_f3_to_gui_queue()
			# DAQ packet: latest sensor values.
			packet = build_packet()
			try:
				socketio.emit("daq_packet", packet)
			except Exception:
				# Keep the thread alive even if Socket.IO isn't ready.
				pass

			# System packet: controller/sequencer snapshot.
			sys_packet = build_system_packet()
			try:
				socketio.emit("system_packet", sys_packet)
			except Exception:
				pass

			next_tick += period_s
			sleep_s = next_tick - time.perf_counter()
			if sleep_s > 0:
				time.sleep(sleep_s)
			else:
				next_tick = time.perf_counter()

	def gui_loop_entrypoint() -> None:
		"""Optional CPU pinning wrapper for the GUI loop thread."""

		if pin_thread_to_cpu is not None and cpu is not None:
			pin_thread_to_cpu(cpu)
		gui_loop_thread()

	# Start the GUI loop once per Flask app instance.
	# (register_socket_handlers can be called multiple times in some setups.)
	if not app.config.get("GUI_LOOP_STARTED"):
		threading.Thread(target=gui_loop_entrypoint, daemon=True, name="gui_loop").start()
		app.config["GUI_LOOP_STARTED"] = True

	@socketio.on("connect")
	def _on_connect() -> None:
		"""Client connected: send initial state so the GUI renders immediately."""

		socketio.emit("server_hello", {"ok": True})
		# Send an immediate packet so the UI doesn't wait up to 100ms.
		socketio.emit("daq_packet", build_packet())
		# Send system state + sequence definitions immediately.
		try:
			defs = app.config.get("SEQUENCE_DEFS")
			if isinstance(defs, list):
				socketio.emit("sequence_definitions", {"sequences": defs})
		except Exception:
			pass
		socketio.emit("system_packet", build_system_packet())

	@socketio.on("manual_step_execute")
	def _on_manual_step_execute(payload: Any) -> None:  # noqa: ANN401
		"""Ack a manual step back to the sequencer/controller.

		Expected payload:
		- {"sequence": <str>, "step_index": <int-like>}
		"""

		q = app.config.get("GUI_TO_F3_QUEUE")
		if q is None:
			socketio.emit("command_reject", {"ok": False, "reason": "gui_to_f3_queue_not_configured"})
			return
		if not isinstance(payload, dict):
			socketio.emit("command_reject", {"ok": False, "reason": "payload_not_object"})
			return
		seq = payload.get("sequence")
		step_index = payload.get("step_index")
		if not isinstance(seq, str) or step_index is None:
			socketio.emit("command_reject", {"ok": False, "reason": "missing_sequence_or_step"})
			return
		try:
			idx = int(step_index)
		except Exception:
			socketio.emit("command_reject", {"ok": False, "reason": "bad_step_index"})
			return

		try:
			q.put({"type": "manual_step_execute", "sequence": seq, "step_index": idx}, timeout=0.1)
		except Exception:
			socketio.emit("command_reject", {"ok": False, "reason": "gui_to_f3_queue_full"})
			return
		socketio.emit("command_accept", {"ok": True, "name": "manual_step_execute"})

	@socketio.on("gui_command")
	def _on_gui_command(payload: Any) -> None:  # noqa: ANN401
		"""Handle general GUI commands.

		The frontend sends a dict payload with a `name` key. We validate and route:
		- Sequencer commands -> `command_queue`
		- Backend runtime controls -> `control_queue`
		"""

		if not isinstance(payload, dict):
			socketio.emit("command_reject", {"ok": False, "reason": "payload_not_object"})
			return

		name = payload.get("name")
		if not isinstance(name, str) or not name:
			socketio.emit("command_reject", {"ok": False, "reason": "missing_name"})
			return

		# Commands intended for the sequencer/controller loop.
		if name in {"fill", "fire"}:
			if command_queue is None:
				socketio.emit("command_reject", {"ok": False, "reason": "command_queue_not_configured"})
				return
			try:
				command_queue.put(name, timeout=0.1)
			except Exception:
				socketio.emit("command_reject", {"ok": False, "reason": "command_queue_full"})
				return
		elif name in {"reset_sequences", "clear_test"}:
			# Used by the GUI to clear sequence state/history so fill/fire can be rerun.
			# Always put it on the command_queue so the controller can clear its
			# history/state when it is not blocked.
			# If (and only if) the controller is currently blocked waiting for a
			# manual-step ack, also put a reset marker on the ack queue to unblock.
			if command_queue is None:
				socketio.emit("command_reject", {"ok": False, "reason": "command_queue_not_configured"})
				return
			try:
				command_queue.put({"type": "reset_sequences"}, timeout=0.1)
			except Exception:
				socketio.emit("command_reject", {"ok": False, "reason": "command_queue_full"})
				return
			try:
				getter = app.config.get("GET_SYSTEM_SNAPSHOT")
				waiting = None
				if callable(getter):
					snap = getter()
					if isinstance(snap, dict):
						waiting = snap.get("waiting_manual")
			except Exception:
				waiting = None
			if isinstance(waiting, dict):
				q_ack = app.config.get("GUI_TO_F3_QUEUE")
				if q_ack is not None:
					try:
						q_ack.put({"type": "reset_sequences"}, timeout=0.1)
					except Exception:
						pass
		elif name == "set_valve":
			if command_queue is None:
				socketio.emit("command_reject", {"ok": False, "reason": "command_queue_not_configured"})
				return
			valve = payload.get("valve")
			state = payload.get("state")
			if not isinstance(valve, str) or not valve:
				socketio.emit("command_reject", {"ok": False, "reason": "missing_valve"})
				return
			if not isinstance(state, str) or not state:
				socketio.emit("command_reject", {"ok": False, "reason": "missing_state"})
				return
			try:
				command_queue.put({"type": "set_valve", "valve": valve, "state": state}, timeout=0.1)
			except Exception:
				socketio.emit("command_reject", {"ok": False, "reason": "command_queue_full"})
				return
		else:
			# Backend runtime control commands: enqueue the full payload object.
			# These are consumed by `GuiCommandHandler` (see backend/gui_command_handler.py).
			if control_queue is None:
				socketio.emit("command_reject", {"ok": False, "reason": "control_queue_not_configured"})
				return
			try:
				control_queue.put(payload, timeout=0.1)
			except Exception:
				socketio.emit("command_reject", {"ok": False, "reason": "control_queue_full"})
				return

		socketio.emit("command_accept", {"ok": True, "name": name})

