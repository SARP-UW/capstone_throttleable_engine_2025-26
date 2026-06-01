from __future__ import annotations

import importlib.util
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from deep_thrott_code.backend.app_factory import parse_args
from deep_thrott_code.backend.daq_runtime import DaqRuntime, drain_queue, emit_system as _emit_system
from deep_thrott_code.backend.gui_command_handler import GuiCommandHandler
from deep_thrott_code.gui.extensions import socketio
from werkzeug.serving import WSGIRequestHandler

try:
	# Prefer the real controller as the source of truth for sequence state.
	# NOTE: This import is expected to work in your environment.
	from deep_thrott_code.f3c.controller import Controller as F3CController  # type: ignore
	from deep_thrott_code.f3c.controller import State as F3CState  # type: ignore
	_F3C_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
	F3CController = None  # type: ignore[assignment]
	F3CState = None  # type: ignore[assignment]
	_F3C_IMPORT_ERROR = exc
		


# ---------------------------------------------------------------------
# CPU pinning notes (Raspberry Pi / Linux)
# ---------------------------------------------------------------------

	# - Core 0: OS + GUI server (can also host one DAQ producer when read path is saturated)
	# - Core 1: DAQ producer / throttle placeholder
	# - Core 2: DAQ producer
	# - Core 3: DAQ consumer + F3C loop (placeholder)

CPU_CORE_0_OS_AND_GUI = 0
CPU_CORE_1_THROTTLE = 1
CPU_CORE_2_DAQ_PRODUCER = 2
CPU_CORE_3_DAQ_CONSUMER_AND_F3 = 3


class _WerkzeugRequestNoiseFilter(logging.Filter):
	"""Filter out per-request access logs but keep startup banner lines."""

	def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
		try:
			msg = record.getMessage()
		except Exception:
			return True
		# Typical access log lines look like:
		# 127.0.0.1 - - [..] "GET /socket.io/?..." 200 -
		if '"GET ' in msg or '"POST ' in msg or '"PUT ' in msg or '"DELETE ' in msg:
			return False
		if msg.startswith('127.0.0.1 ') or msg.startswith('::1 '):
			return False
		return True


class _QuietDisconnectWSGIRequestHandler(WSGIRequestHandler):
	"""Suppress known dev-server disconnect assertions from aborted refreshes."""

	def run_wsgi(self) -> None:
		try:
			super().run_wsgi()
		except AssertionError as exc:
			if str(exc) == 'write() before start_response':
				return
			raise
		except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
			return


def pin_current_thread_to_cpu(cpu_index: int) -> None:
	"""Best-effort pinning for the *calling thread* (Linux-only)."""
	try:
		os.sched_setaffinity(0, {int(cpu_index)})
	except Exception:
		return


def main() -> None:
	cfg = parse_args()

	if not cfg.no_gui_server and getattr(socketio, "is_dummy", False):
		raise RuntimeError(
			"flask_socketio is required for the backend service. "
			"Install `flask-socketio` (and deps) in this environment."
		)

	gui_queue: queue.Queue = queue.Queue(maxsize=1000)

	# I forgot why i made these separate 
	sequencer_command_queue: queue.Queue = queue.Queue(maxsize=100)
	sequencer_ack_queue: queue.Queue = queue.Queue(maxsize=100)
	control_queue: queue.Queue = queue.Queue(maxsize=100)
	f3_to_gui_queue: queue.Queue = queue.Queue(maxsize=100)
	
	sequences_path = Path(__file__).resolve().parent / "config" / "sequences.yaml"
	hardware_path = Path(__file__).resolve().parent / "config" / "hardware.yml"

	sequence_defs_for_gui: list[dict[str, Any]] = []
	get_system_snapshot: Any | None = None
	controller_for_snapshot: Any | None = None

	f3_controller: Any | None = None
	if cfg.no_sequencer:
		print("Sequencer disabled (--no-sequencer): running DAQ backend only.")
	elif F3CController is not None and F3CState is not None:
		try:
			f3_controller = F3CController(
				hardware_config_path=str(hardware_path),
				sequence_config_path=str(sequences_path),
				f3c_to_gui_queue=f3_to_gui_queue,
				command_queue=sequencer_command_queue,
				ack_queue=sequencer_ack_queue,
				system_state=F3CState.IDLE,
			)
		except Exception as exc:
			print(f"Warning: F3C controller unavailable ({exc}); continuing without sequencer.")
			f3_controller = None
	elif _F3C_IMPORT_ERROR is not None:
		print(
			f"Warning: F3C controller failed to import ({_F3C_IMPORT_ERROR}); "
			"continuing without sequencer."
		)

	if f3_controller is not None:
		# bring daqruntime back out to main
		loop_forever = getattr(f3_controller, "loop_forever", None)
		if callable(loop_forever):
			def f3_controller_entrypoint() -> None:
				pin_current_thread_to_cpu(CPU_CORE_3_DAQ_CONSUMER_AND_F3)
				loop_forever()

			threading.Thread(target=f3_controller_entrypoint, daemon=True, name="f3c_loop").start()

		try:
			sequence_defs_for_gui = f3_controller.get_sequence_definitions_for_gui()
		except Exception:
			sequence_defs_for_gui = []
		get_system_snapshot = getattr(f3_controller, "snapshot", None)

	sample_queue: queue.Queue = queue.Queue(maxsize=1000)
	daq = DaqRuntime(
		gui_queue=gui_queue,
		sample_queue=sample_queue,
		emit_system_fn=_emit_system,
		drain_queue_fn=drain_queue,
		pin_thread_to_cpu=pin_current_thread_to_cpu,
		producer_cpu=CPU_CORE_2_DAQ_PRODUCER,
		producer_cpus=(CPU_CORE_1_THROTTLE, CPU_CORE_2_DAQ_PRODUCER, CPU_CORE_3_DAQ_CONSUMER_AND_F3),
		consumer_cpu=CPU_CORE_3_DAQ_CONSUMER_AND_F3,
	)

	# -----------------------------------------------------------------
	# TODO: Throttle control loop add
	# -----------------------------------------------------------------

	controller_ref: dict[str, GuiCommandHandler | None] = {"value": None}
	clear_latest_daq_state: Any | None = None

	def _backend_meta() -> dict[str, Any]:
		meta = daq.snapshot_meta()
		controller = controller_ref["value"]
		if controller is not None:
			meta.update(controller.snapshot_meta())
		return meta

	if not cfg.no_gui_server:
		from deep_thrott_code.gui.sockets import register_socket_handlers
		from flask import Flask

		app = Flask(__name__)
		app.config["SECRET_KEY"] = "dev"
		socketio.init_app(app)

		register_socket_handlers(
			socketio,
			app,
			gui_queue=gui_queue,
			command_queue=sequencer_command_queue,
			control_queue=control_queue,
			f3_to_gui_queue=f3_to_gui_queue,
			gui_to_f3_queue=sequencer_ack_queue,
			get_system_snapshot=get_system_snapshot,
			sequence_defs=sequence_defs_for_gui,
			backend_meta_getter=_backend_meta,
			pin_thread_to_cpu=pin_current_thread_to_cpu,
			cpu=CPU_CORE_0_OS_AND_GUI,
		)
		clear_latest_daq_state = app.config.get("CLEAR_LATEST_STATES")

	controller = GuiCommandHandler(
		control_queue=control_queue,
		emit_system=_emit_system,
		start_log=daq.start,
		stop_log=daq.stop,
		is_running=daq.is_running,
		zero_sensor=daq.zero_sensor,
		clear_daq_state=clear_latest_daq_state,
	)
	controller_ref["value"] = controller

	controller.set_simulation_enabled(cfg.simulation)
	threading.Thread(target=controller.command_loop_forever, daemon=True, 
				  name="backend_command_loop").start()

	if cfg.autostart:
		daq.start(cfg.simulation)

	if cfg.no_gui_server:
		print("Backend running without GUI server (--no-gui-server).")
		print("Use Ctrl+C to stop. If CPU stays low in this mode, the web/socket server is the culprit.")
		try:
			while True:
				time.sleep(1.0)
		except KeyboardInterrupt:
			print("Backend shutdown requested (Ctrl+C).")
		finally:
			try:
				if daq.is_running():
					daq.stop()
			except Exception:
				pass

			try:
				if f3_controller is not None:
					shutdown = getattr(f3_controller, "shutdown", None)
					if callable(shutdown):
						shutdown()
			except Exception:
				pass
		return

	print(f"Backend listening on http://{cfg.host}:{cfg.port} (Socket.IO)")
	print(f"Socket.IO async mode: {getattr(socketio, 'async_mode', 'unknown')}")
	if getattr(socketio, 'async_mode', '') == 'threading' and importlib.util.find_spec("simple_websocket") is None:
		print(
			"Warning: simple-websocket is not installed, so Flask-SocketIO will fall back "
			"to HTTP long-polling in threading mode. This can drive high CPU when the GUI connects."
		)

	# Keep terminal output readable: filter out per-request logs (polling spam)
	# while keeping the startup banner ("Running on http://...") visible.
	werk = logging.getLogger("werkzeug")
	werk.setLevel(logging.INFO)
	werk.addFilter(_WerkzeugRequestNoiseFilter())
	logging.getLogger("engineio").setLevel(logging.ERROR)
	logging.getLogger("socketio").setLevel(logging.ERROR)

	run_kwargs: dict[str, Any] = {
		'app': app,
		'host': cfg.host,
		'port': cfg.port,
		'debug': cfg.debug,
		'use_reloader': False,
		'allow_unsafe_werkzeug': True,
		'log_output': True,
	}
	if getattr(socketio, 'async_mode', '') == 'threading':
		run_kwargs['request_handler'] = _QuietDisconnectWSGIRequestHandler

	try:
		socketio.run(**run_kwargs)
	except KeyboardInterrupt:
		print("Backend shutdown requested (Ctrl+C).")
	finally:
		try:
			if daq.is_running():
				daq.stop()
		except Exception:
			pass

		try:
			if f3_controller is not None:
				shutdown = getattr(f3_controller, "shutdown", None)
				if callable(shutdown):
					shutdown()
		except Exception:
			pass

if __name__ == "__main__":
	main()

