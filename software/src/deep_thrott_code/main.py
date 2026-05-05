from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from typing import Any

from deep_thrott_code.backend.app_factory import parse_args
from deep_thrott_code.backend.daq_runtime import DaqRuntime, drain_queue, emit_system as _emit_system
from deep_thrott_code.backend.gui_command_handler import GuiCommandHandler
from deep_thrott_code.gui.extensions import socketio

try:
	# Prefer the real controller as the source of truth for sequence state.
	# NOTE: This import is expected to work in your environment.
	from deep_thrott_code.f3c.controller import Controller as F3CController  # type: ignore
	from deep_thrott_code.f3c.controller import State as F3CState  # type: ignore
except Exception:  # pragma: no cover
	F3CController = None  # type: ignore[assignment]
	F3CState = None  # type: ignore[assignment]
		


# ---------------------------------------------------------------------
# CPU pinning notes (Raspberry Pi / Linux)
# ---------------------------------------------------------------------

# - Core 0: OS + GUI server
# - Core 1: throttle control loop (placeholder)
# - Core 2: DAQ producer
# - Core 3: DAQ consumer + F3C loop (placeholder)

CPU_CORE_1_OS_AND_GUI = 0
CPU_CORE_2_THROTTLE = 1
CPU_CORE_3_DAQ_PRODUCER = 2
CPU_CORE_4_DAQ_CONSUMER_AND_F3 = 3


def pin_current_thread_to_cpu(cpu_index: int) -> None:
	"""Best-effort pinning for the *calling thread* (Linux-only)."""
	try:
		os.sched_setaffinity(0, {int(cpu_index)})
	except Exception:
		return


def main() -> None:
	cfg = parse_args()

	if getattr(socketio, "is_dummy", False):
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
	if F3CController is not None and F3CState is not None:
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

	if f3_controller is not None:
		# TODO: don't start controller until start log is pressed,
		# bring daqruntime back out to main
		loop_forever = getattr(f3_controller, "loop_forever", None)
		if callable(loop_forever):
			def f3_controller_entrypoint() -> None:
				pin_current_thread_to_cpu(CPU_CORE_4_DAQ_CONSUMER_AND_F3)
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
		producer_cpu=CPU_CORE_3_DAQ_PRODUCER,
		consumer_cpu=CPU_CORE_4_DAQ_CONSUMER_AND_F3,
	)

	# -----------------------------------------------------------------
	# TODO: Throttle control loop add
	# -----------------------------------------------------------------

	# Gui stuffs

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
		pin_thread_to_cpu = pin_current_thread_to_cpu,
		cpu=CPU_CORE_1_OS_AND_GUI,
	)

	controller = GuiCommandHandler(
		control_queue=control_queue,
		emit_system=_emit_system,
		start_log=daq.start,
		stop_log=daq.stop,
		is_running=daq.is_running,
	)

	controller.set_simulation_enabled(cfg.simulation)
	threading.Thread(target=controller.command_loop_forever, daemon=True, 
				  name="backend_command_loop").start()

	if cfg.autostart:
		daq.start(cfg.simulation)

	print(f"Backend listening on http://{cfg.host}:{cfg.port} (Socket.IO)")
	socketio.run(app, host=cfg.host, port=cfg.port, debug=cfg.debug, use_reloader=False)

if __name__ == "__main__":
	main()

