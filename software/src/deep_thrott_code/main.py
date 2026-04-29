from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

from deep_thrott_code.backend_app import DaqRuntime, create_backend_app, drain_queue, emit_system as _emit_system, parse_args
from deep_thrott_code.backend_service import BackendController
from deep_thrott_code.gui.extensions import socketio
from deep_thrott_code.sequence_runtime import SequenceRuntime, load_sequences_yaml


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
	command_queue: queue.Queue = queue.Queue(maxsize=100)
	control_queue: queue.Queue = queue.Queue(maxsize=100)
	f3_to_gui_queue: queue.Queue = queue.Queue(maxsize=100)
	gui_to_f3_queue: queue.Queue = queue.Queue(maxsize=100)

	# -----------------------------------------------------------------
	# Sequence definitions + manual execute handshake (GUI-driven)
	# -----------------------------------------------------------------
	# NOTE: This is a lightweight runner that drives the GUI tabs and
	# the manual-execute handshake *without* editing `f3c/controller.py`.
	# TODO: Replace with real F3C controller integration.
	
	sequences_path = Path(__file__).resolve().parent / "config" / "sequences.yaml"
	try:
		sequences = load_sequences_yaml(sequences_path)
	except Exception as e:
		_emit_system(f"Failed to load sequences.yaml: {e}")
		sequences = {"idle": {}}  # type: ignore[assignment]
		sequence_runtime = None
		sequence_defs_for_gui: list[dict] = []
		get_system_snapshot = None
	else:
		sequence_runtime = SequenceRuntime(
			sequences=sequences,
			command_queue=command_queue,
			f3_to_gui_queue=f3_to_gui_queue,
			gui_to_f3_queue=gui_to_f3_queue,
		)
		sequence_defs_for_gui = sequence_runtime.get_sequence_defs_for_gui()
		get_system_snapshot = sequence_runtime.snapshot
		threading.Thread(
			target=sequence_runtime.loop_forever,
			daemon=True,
			name="sequence_runtime",
		).start()

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

	# -----------------------------------------------------------------
	# TODO: F3C loop add
	# -----------------------------------------------------------------

	app = create_backend_app(
		gui_queue=gui_queue,
		command_queue=command_queue,
		control_queue=control_queue,
		f3_to_gui_queue=f3_to_gui_queue,
		gui_to_f3_queue=gui_to_f3_queue,
		get_system_snapshot=get_system_snapshot,
		sequence_defs=sequence_defs_for_gui,
	)
	controller = BackendController(
		control_queue=control_queue,
		emit_system=_emit_system,
		start_log=daq.start,
		stop_log=daq.stop,
		is_running=daq.is_running,
	)

	controller.set_simulation_enabled(cfg.simulation)
	threading.Thread(target=controller.command_loop_forever, daemon=True, name="backend_command_loop").start()

	if cfg.autostart:
		daq.start(cfg.simulation)

	print(f"Backend listening on http://{cfg.host}:{cfg.port} (Socket.IO)")
	socketio.run(app, host=cfg.host, port=cfg.port, debug=cfg.debug, use_reloader=False)

if __name__ == "__main__":
	main()

