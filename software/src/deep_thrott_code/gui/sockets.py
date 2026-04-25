
from __future__ import annotations

import queue
import threading
import time
from typing import Any


def _sample_to_json(sample: Any) -> dict[str, Any]:  # noqa: ANN401
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

	latest_lock = threading.Lock()
	latest_states: dict[str, dict[str, Any]] = {}

	# Expose for other modules / debugging.
	app.config["LATEST_STATES"] = latest_states
	app.config["LATEST_LOCK"] = latest_lock
	app.config["GUI_QUEUE"] = gui_queue
	app.config["COMMAND_QUEUE"] = command_queue

	def drain_gui_queue() -> int:
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
		with latest_lock:
			states_copy = dict(latest_states)
		return {"t_wall": time.time(), "states": states_copy}

	def gui_loop_thread() -> None:
		period_s = 0.1
		next_tick = time.perf_counter()
		while True:
			drain_gui_queue()
			packet = build_packet()
			try:
				socketio.emit("daq_packet", packet)
			except Exception:
				# Keep the thread alive even if Socket.IO isn't ready.
				pass

			next_tick += period_s
			sleep_s = next_tick - time.perf_counter()
			if sleep_s > 0:
				time.sleep(sleep_s)
			else:
				next_tick = time.perf_counter()

	# Start the GUI loop once.
	if not app.config.get("GUI_LOOP_STARTED"):
		threading.Thread(target=gui_loop_thread, daemon=True, name="gui_loop").start()
		app.config["GUI_LOOP_STARTED"] = True

	@socketio.on("connect")
	def _on_connect() -> None:
		socketio.emit("server_hello", {"ok": True})
		# Send an immediate packet so the UI doesn't wait up to 100ms.
		socketio.emit("daq_packet", build_packet())

	@socketio.on("gui_command")
	def _on_gui_command(payload: Any) -> None:  # noqa: ANN401
		if not isinstance(payload, dict):
			socketio.emit("command_reject", {"ok": False, "reason": "payload_not_object"})
			return

		name = payload.get("name")
		if not isinstance(name, str) or not name:
			socketio.emit("command_reject", {"ok": False, "reason": "missing_name"})
			return

		if command_queue is None:
			socketio.emit("command_reject", {"ok": False, "reason": "command_queue_not_configured"})
			return

		try:
			command_queue.put(payload, timeout=0.1)
		except Exception:
			socketio.emit("command_reject", {"ok": False, "reason": "command_queue_full"})
			return

		socketio.emit("command_accept", {"ok": True, "name": name})

