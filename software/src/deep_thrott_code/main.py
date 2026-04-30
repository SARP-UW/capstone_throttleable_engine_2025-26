from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from typing import Any

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

	def _load_controller_sequences_like_yaml(path: Path) -> dict[str, dict[str, Any]]:
		"""Load sequences into the same shape as `Controller.sequences`.

		We intentionally do NOT import `deep_thrott_code.f3c.controller.Controller` here
		because importing it on Windows currently fails due to `RPi.GPIO` imports.

		Returns: {sequence_name: raw_sequence_dict}
		"""
		try:
			import yaml  # type: ignore
		except Exception:
			return {}
		try:
			with path.open("r", encoding="utf-8") as f:
				doc = yaml.safe_load(f)
		except Exception:
			return {}
		if not isinstance(doc, dict):
			return {}
		seqs = doc.get("sequences")
		if not isinstance(seqs, list):
			return {}
		out: dict[str, dict[str, Any]] = {}
		for s in seqs:
			if not isinstance(s, dict):
				continue
			name = s.get("name")
			if not isinstance(name, str) or not name:
				continue
			out[name] = s
		return out

	def _sequence_defs_for_gui_from_controller_sequences(
		controller_sequences: dict[str, dict[str, Any]],
	) -> list[dict[str, Any]]:
		"""Convert controller-style sequences dict into GUI `sequence_definitions` payload."""
		ordered_keys = ["idle", "fill", "fire"]
		defs: list[dict[str, Any]] = []
		# Normalize lookup: controller uses original YAML names; we want lowercase keys.
		lower_map: dict[str, dict[str, Any]] = {}
		for k, v in controller_sequences.items():
			if isinstance(k, str) and isinstance(v, dict):
				lower_map[k.lower()] = v

		for key in ordered_keys:
			seq_raw = lower_map.get(key)
			seq_name = key.upper()
			steps_raw: list[Any] = []
			if isinstance(seq_raw, dict):
				name_field = seq_raw.get("name")
				if isinstance(name_field, str) and name_field:
					seq_name = name_field.upper()
				steps_field = seq_raw.get("steps")
				if isinstance(steps_field, list):
					steps_raw = steps_field

			steps: list[dict[str, Any]] = []
			for i, step in enumerate(steps_raw):
				if not isinstance(step, dict):
					continue
				# Controller steps typically use `valve_id`; our GUI YAML uses `valve`.
				valve = step.get("valve_id")
				if valve is None:
					valve = step.get("valve")
				valve_str = str(valve).upper() if valve is not None else ""
				action = step.get("action")
				action_str = str(action).lower() if action is not None else ""
				time_delay = step.get("time_delay", 0.0)
				try:
					time_delay_s = float(time_delay or 0.0)
				except Exception:
					time_delay_s = 0.0
				user_input = bool(step.get("user_input", False))
				condition_valve = step.get("condition_valve")
				condition_state = step.get("condition_state")
				system_state = step.get("system_state")
				system_state_str = str(system_state).upper() if system_state is not None else seq_name
				steps.append(
					{
						"index": int(i),
						"valve": valve_str,
						"action": action_str,
						"time_delay_s": time_delay_s,
						"user_input": user_input,
						"condition_valve": str(condition_valve).upper() if condition_valve else None,
						"condition_state": str(condition_state) if condition_state is not None else None,
						"system_state": system_state_str,
					}
				)

			defs.append({"name": seq_name, "key": key, "steps": steps})

		return defs

	controller_sequences_like = _load_controller_sequences_like_yaml(sequences_path)
	sequence_defs_for_gui_from_controller = _sequence_defs_for_gui_from_controller_sequences(controller_sequences_like)
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
		# GUI sequence tabs/steps should reflect the controller's view of sequences.
		# For now we load controller-like YAML directly to avoid importing `f3c` on Windows.
		sequence_defs_for_gui = (
			sequence_defs_for_gui_from_controller
			if sequence_defs_for_gui_from_controller
			else sequence_runtime.get_sequence_defs_for_gui()
		)
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

