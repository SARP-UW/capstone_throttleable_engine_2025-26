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
"""

import argparse
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass

from flask import Flask


@dataclass(frozen=True)
class BackendConfig:
	host: str
	port: int
	debug: bool
	autostart: bool
	simulation: bool


def parse_args() -> BackendConfig:
	"""Parse CLI flags for running the backend as a standalone process."""

	parser = argparse.ArgumentParser(description="Deep Thrott Code backend (DAQ + Socket.IO)")
	parser.add_argument("--host", default="0.0.0.0", help="Bind host (0.0.0.0 to listen on LAN)")
	parser.add_argument(
		"--port",
		type=int,
		default=6001,
		help="Bind port for backend Socket.IO (6000 is browser-unsafe; default 6001)",
	)
	parser.add_argument("--debug", action="store_true", help="Enable Flask debug")
	parser.add_argument("--autostart", action="store_true", help="Start logging immediately")
	parser.add_argument(
		"--simulation",
		action="store_true",
		help="Default to Simulation Mode ON at startup (still changeable via GUI)",
	)
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

	# Local imports to keep this module importable in more environments.
	from deep_thrott_code.gui.extensions import socketio  # noqa: PLC0415
	from deep_thrott_code.gui.sockets import register_socket_handlers  # noqa: PLC0415

	app = Flask(__name__)
	app.config["SECRET_KEY"] = "dev"

	socketio.init_app(app)
	register_socket_handlers(
		socketio,
		app,
		gui_queue=gui_queue,
		command_queue=command_queue,
		control_queue=control_queue,
		f3_to_gui_queue=f3_to_gui_queue,
		gui_to_f3_queue=gui_to_f3_queue,
		get_system_snapshot=get_system_snapshot,
		sequence_defs=sequence_defs,
	)
	return app


def drain_queue(q: queue.Queue) -> None:
	"""Best-effort queue drain used to drop stale samples on restarts."""

	while True:
		try:
			q.get_nowait()
		except Exception:
			break
		else:
			try:
				q.task_done()
			except Exception:
				pass


def emit_system(text: str) -> None:
	"""Emit a one-line system message to the GUI (best-effort)."""

	# Local import so this module stays importable without Flask-SocketIO.
	from deep_thrott_code.gui.extensions import socketio  # noqa: PLC0415

	try:
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
		self._gui_queue = gui_queue
		self._sample_queue = sample_queue
		self._emit_system = emit_system_fn
		self._drain_queue = drain_queue_fn
		self._pin_thread_to_cpu = pin_thread_to_cpu
		self._producer_cpu = int(producer_cpu)
		self._consumer_cpu = int(consumer_cpu)
		self._log_path = str(log_path)

		self._lock = threading.Lock()
		self._running = False
		self._stop_event: threading.Event | None = None
		self._producer_thread: threading.Thread | None = None
		self._consumer_thread: threading.Thread | None = None
		self._logger = None
		self._state_store = None

	def is_running(self) -> bool:
		with self._lock:
			return bool(self._running)

	def start(self, simulation: bool) -> None:
		"""Start DAQ threads and begin emitting samples to `gui_queue`.

		The producer reads sensors (or sim sources) into `sample_queue`.
		The consumer converts samples into GUI-friendly updates and logs to CSV.
		"""

		from deep_thrott_code.daq.services.loop import consumer_loop, producer_loop  # noqa: PLC0415
		from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
		from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
		from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415

		with self._lock:
			if self._running:
				self._emit_system("Log already running.")
				return

		try:
			sensors = build_sensors(simulation=bool(simulation))
		except Exception as e:
			self._emit_system(str(e))
			return

		sensor_map = build_sensor_map(sensors)
		stop_event = threading.Event()
		state_store = StateStore()
		logger = CsvLogger(self._log_path, flush_every=25, fsync_every_flush=False)

		self._drain_queue(self._sample_queue)
		self._drain_queue(self._gui_queue)

		def producer_entrypoint() -> None:
			# CPU pinning is optional; on Windows this may no-op depending on impl.
			self._pin_thread_to_cpu(self._producer_cpu)
			producer_loop(sensors, self._sample_queue, stop_event, 50.0)

		def consumer_entrypoint() -> None:
			# The consumer is the only place that touches StateStore + logger.
			self._pin_thread_to_cpu(self._consumer_cpu)
			consumer_loop(self._sample_queue, self._gui_queue, state_store, logger, stop_event, sensor_map)

		producer_thread = threading.Thread(target=producer_entrypoint, daemon=True, name="producer")
		consumer_thread = threading.Thread(target=consumer_entrypoint, daemon=True, name="consumer")
		producer_thread.start()
		consumer_thread.start()

		with self._lock:
			self._running = True
			self._stop_event = stop_event
			self._producer_thread = producer_thread
			self._consumer_thread = consumer_thread
			self._logger = logger
			self._state_store = state_store

		self._emit_system(f"Backend log started ({'SIM' if simulation else 'ADC'} mode).")

	def stop(self) -> None:
		"""Stop DAQ threads and close the logger (best-effort)."""

		with self._lock:
			if not self._running:
				self._emit_system("No log running.")
				return
			stop_event = self._stop_event
			producer_thread = self._producer_thread
			consumer_thread = self._consumer_thread
			logger = self._logger
			self._running = False
			self._stop_event = None
			self._producer_thread = None
			self._consumer_thread = None
			self._logger = None
			self._state_store = None

		if stop_event is not None:
			stop_event.set()
		if producer_thread is not None:
			producer_thread.join(timeout=1.0)
		if consumer_thread is not None:
			consumer_thread.join(timeout=1.0)

		try:
			if logger is not None:
				logger.close()
		except Exception:
			pass

		self._drain_queue(self._sample_queue)
		self._drain_queue(self._gui_queue)
		self._emit_system("Backend log stopped.")
