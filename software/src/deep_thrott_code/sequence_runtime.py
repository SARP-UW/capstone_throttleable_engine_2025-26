from __future__ import annotations

"""YAML-driven sequencing runtime used by the GUI demo.

TODO (target architecture): move sequencing ownership into `f3c/controller.py`.

If the GUI backend should be *read-only* (only reading a Controller instance,
not owning state transitions), the Controller should grow a few things.

- Thread-safety:
	- Add a `threading.Lock` (or `RLock`) that protects all sequencing state.
	- Provide a single `snapshot()` method that returns a JSON-serializable dict.
	  (So the Socket.IO loop can read state without touching attributes directly.)

- Stable GUI snapshot schema (match what `gui/static/main.js` expects):
	- `system_state`: string (e.g. "IDLE", "FILL", "FIRE", ...)
	- `active_sequence`: string key ("idle"/"fill"/"fire")
	- `current_step_index`: int | null
	- `history`: list of {sequence, step_index, status, t_wall}
	- `waiting_manual`: {sequence, step_index} | null

- Structured history + indexing:
	- Track step index explicitly as an integer (not just (valve_id, action)).
	- Append to a structured history list with status updates (READY/EXECUTING/COMPLETED/etc.).
	- Optionally reset/segment history per sequence run so the GUI can show checkmarks
	  for the current sequence only.

- Manual-step handshake:
	- Expose `waiting_manual` when paused for user input.
	- Provide a dedicated method like `ack_manual_step(sequence, step_index)` OR
	  separate inbound/outbound queues so GUI acks cannot be confused with new commands.

- Importability / cross-platform:
	- Avoid importing `RPi.GPIO` at module import time on non-Pi environments.
	  (Right now importing `f3c/controller.py` pulls in `f3c/valve.py` which imports
	  `RPi.GPIO`, so the backend cannot even import the Controller on Windows.)

- Sequences shape:
	- If `controller.sequences` remains a raw YAML dict ({name: {...}}), that's fine;
	  the GUI backend can adapt it. A `StepDef` dataclass is not strictly necessary,
	  but adding typed step objects can make validation and indexing easier.

This module is intentionally *self-contained* and *lightweight*:
- It loads human-editable sequence definitions from `sequences.yaml`.
- It runs one sequence at a time in response to high-level commands ("fill", "fire").
- It exposes a thread-safe `snapshot()` for the GUI to display state.
- It supports a simple manual-step handshake: backend notifies the GUI that a
	step needs user action, then blocks until the GUI acknowledges "Execute".

Important: this is currently a placeholder for real F3C/controller integration.
No actual valve actuation or sensor/condition enforcement happens here yet.
"""

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StepDef:
	"""One step in a named sequence.

	Fields map 1:1 to YAML step keys (with light normalization):
	- `valve` / `action`: displayed by the GUI and (eventually) used for actuation.
	- `time_delay_s`: time to sleep after the step executes (placeholder timing).
	- `user_input`: if true, the runtime pauses until the GUI acks "Execute".
	- `condition_*`: reserved for future validation (not enforced yet).
	- `system_state`: what the GUI should show while this step is active.
	"""

	valve: str
	action: str
	time_delay_s: float
	user_input: bool
	condition_valve: str | None
	condition_state: str | None
	system_state: str


@dataclass(frozen=True)
class SequenceDef:
	"""A named group of ordered `StepDef`s.

	The `key` for a sequence is the dict key returned by `load_sequences_yaml()`
	(e.g. "fill" / "fire"), while `name` is the display name from YAML.
	"""

	name: str
	steps: list[StepDef]


def _as_str_or_none(v: Any) -> str | None:  # noqa: ANN401
	if v is None:
		return None
	if isinstance(v, str):
		return v
	return str(v)


def load_sequences_yaml(path: str | Path) -> dict[str, SequenceDef]:
	"""Load sequences from a YAML file.

	Returns a dict keyed by lowercase sequence name ("fill", "fire", ...).
	Also guarantees an "idle" sequence exists so the GUI can always render tabs.
	"""

	try:
		import yaml  # type: ignore
	except Exception as e:  # pragma: no cover
		raise RuntimeError("PyYAML is required to load sequences.yaml") from e

	p = Path(path)
	with p.open("r", encoding="utf-8") as f:
		doc = yaml.safe_load(f)

	if not isinstance(doc, dict):
		raise ValueError("sequences.yaml root must be an object")

	seqs_raw = doc.get("sequences")
	if not isinstance(seqs_raw, list):
		raise ValueError("sequences.yaml must contain a 'sequences' list")

	out: dict[str, SequenceDef] = {}
	for seq in seqs_raw:
		if not isinstance(seq, dict):
			continue
		name = seq.get("name")
		if not isinstance(name, str) or not name:
			continue

		steps_raw = seq.get("steps")
		steps: list[StepDef] = []
		if isinstance(steps_raw, list):
			for step in steps_raw:
				if not isinstance(step, dict):
					continue

				# Required keys (for now): `valve` + `action`.
				# Everything else is optional and gets a safe default.
				valve = step.get("valve")
				action = step.get("action")
				if not isinstance(valve, str) or not isinstance(action, str):
					continue
				time_delay = step.get("time_delay", 0.0)
				try:
					time_delay_s = float(time_delay or 0.0)
				except Exception:
					time_delay_s = 0.0
				user_input = bool(step.get("user_input", False))
				condition_valve = _as_str_or_none(step.get("condition_valve"))
				condition_state = _as_str_or_none(step.get("condition_state"))
				system_state = step.get("system_state")
				if not isinstance(system_state, str) or not system_state:
					# If omitted, default the displayed state to the sequence name.
					system_state = name

				steps.append(
					StepDef(
						valve=valve,
						action=action,
						time_delay_s=time_delay_s,
						user_input=user_input,
						condition_valve=condition_valve,
						condition_state=condition_state,
						system_state=system_state,
					)
				)

		out[name.lower()] = SequenceDef(name=name, steps=steps)

	# Always provide an idle sequence for the GUI tabs.
	out.setdefault("idle", SequenceDef(name="idle", steps=[]))
	return out


class SequenceRuntime:
	"""Minimal sequence runner + GUI handshake.

	It provides enough state for the GUI to:
	- Render the Idle/Fill/Fire tabs from sequences.yaml
	- Highlight the active sequence and current step
	- Pause on `user_input: true` steps and wait for a GUI "Execute" ack

	TODO (placeholder): Replace this with real integration with the F3C controller
	and real valve actuation + condition checking.
	"""

	def __init__(
		self,
		*,
		sequences: dict[str, SequenceDef],
		command_queue: queue.Queue,
		f3_to_gui_queue: queue.Queue,
		gui_to_f3_queue: queue.Queue,
	) -> None:
		# Communication primitives used by the backend app:
		# - `command_queue`: receives high-level commands ("fill", "fire") from GUI.
		# - `f3_to_gui_queue`: runtime -> GUI messages (manual step required).
		# - `gui_to_f3_queue`: GUI -> runtime acknowledgements (manual execute).
		self._sequences = dict(sequences)
		self._command_queue = command_queue
		self._f3_to_gui_queue = f3_to_gui_queue
		self._gui_to_f3_queue = gui_to_f3_queue

		self._lock = threading.Lock()
		# State below is consumed by the GUI via `snapshot()`.
		# Everything is protected by `_lock` because the runtime runs in its own
		# thread while the Socket.IO emitter reads concurrently.
		self._system_state = "IDLE"
		self._active_sequence: str = "idle"
		self._current_step_index: int | None = None
		self._history: list[dict[str, Any]] = []
		self._waiting_manual: dict[str, Any] | None = None

	def get_sequence_defs_for_gui(self) -> list[dict[str, Any]]:
		"""Return browser-friendly JSON describing sequences/steps.

		This is sent once on Socket.IO connect as `sequence_definitions` and used
		to render the Idle/Fill/Fire tabs.
		"""

		# Keep this stable and browser-friendly (pure JSON).
		ordered = ["idle", "fill", "fire"]
		defs: list[dict[str, Any]] = []
		for key in ordered:
			seq = self._sequences.get(key)
			if not seq:
				seq = SequenceDef(name=key, steps=[])
			defs.append(
				{
					"name": seq.name.upper(),
					"key": key,
					"steps": [
						{
							"index": i,
							"valve": s.valve.upper(),
							"action": s.action.lower(),
							"time_delay_s": s.time_delay_s,
							"user_input": bool(s.user_input),
							"condition_valve": (s.condition_valve.upper() if s.condition_valve else None),
							"condition_state": s.condition_state,
							"system_state": s.system_state.upper(),
						}
						for i, s in enumerate(seq.steps)
					],
				}
			)
		return defs

	def snapshot(self) -> dict[str, Any]:
		"""Thread-safe snapshot used for the GUI's `system_packet`.

		Note: `history` is a list of small dicts to keep it JSON-serializable.
		"""

		with self._lock:
			return {
				"system_state": str(self._system_state),
				"active_sequence": str(self._active_sequence),
				"current_step_index": self._current_step_index,
				"history": list(self._history),
				"waiting_manual": dict(self._waiting_manual) if self._waiting_manual else None,
			}

	def _set_active(self, sequence_key: str) -> None:
		# Reset all per-run state when a new sequence starts.
		with self._lock:
			self._active_sequence = sequence_key
			self._current_step_index = None
			self._waiting_manual = None
			self._system_state = sequence_key.upper() if sequence_key != "idle" else "IDLE"
			self._history = []

	def _record_history(self, *, sequence_key: str, step_index: int, status: str) -> None:
		with self._lock:
			self._history.append(
				{
					"sequence": sequence_key,
					"step_index": int(step_index),
					"status": str(status),
					"t_wall": time.time(),
				}
			)

	def _set_current_step(self, idx: int | None) -> None:
		with self._lock:
			self._current_step_index = idx

	def _set_system_state(self, state: str) -> None:
		with self._lock:
			self._system_state = str(state).upper()

	def _set_waiting_manual(self, info: dict[str, Any] | None) -> None:
		with self._lock:
			self._waiting_manual = dict(info) if info else None

	def _wait_for_manual_execute(self, *, sequence_key: str, step_index: int) -> None:
		"""Block until GUI acknowledges manual step execution.

		Protocol:
		- runtime -> GUI: enqueue a dict on `f3_to_gui_queue` with type
		  `manual_step_required`.
		- GUI -> runtime: Socket.IO handler enqueues `manual_step_execute` dict onto
		  `gui_to_f3_queue`.
		- runtime: waits until it sees a matching {sequence, step_index} ack.
		"""

		# Notify the GUI that this step requires user action.
		msg = {
			"type": "manual_step_required",
			"sequence": sequence_key,
			"step_index": int(step_index),
			"message": "Manual step required. Perform the required checks, then click Execute.",
		}
		self._set_waiting_manual({"sequence": sequence_key, "step_index": int(step_index)})
		try:
			self._f3_to_gui_queue.put(msg, timeout=0.1)
		except Exception:
			pass

		# Block until the GUI acknowledges the step.
		while True:
			ack = self._gui_to_f3_queue.get()
			try:
				# Ignore unrelated acks (other steps/sequences) and keep waiting.
				if not isinstance(ack, dict):
					continue
				if ack.get("type") != "manual_step_execute":
					continue
				if ack.get("sequence") != sequence_key:
					continue
				if int(ack.get("step_index", -1)) != int(step_index):
					continue
				break
			finally:
				try:
					self._gui_to_f3_queue.task_done()
				except Exception:
					pass

		self._set_waiting_manual(None)

	def _run_sequence(self, sequence_key: str) -> None:
		"""Run a single sequence to completion.

		This method is intentionally synchronous: it updates state, optionally
		blocks on manual steps, sleeps for delays, then returns.
		"""

		seq = self._sequences.get(sequence_key)
		if not seq:
			return

		self._set_active(sequence_key)

		for idx, step in enumerate(seq.steps):
			# These fields are what the GUI highlights while running.
			self._set_current_step(idx)
			self._set_system_state(step.system_state)
			self._record_history(sequence_key=sequence_key, step_index=idx, status="READY")

			# Placeholder: validate step conditions here (valve state, sensors, etc.).
			# TODO: integrate with real valve state + controller.

			if step.user_input:
				self._record_history(sequence_key=sequence_key, step_index=idx, status="WAITING_USER")
				self._wait_for_manual_execute(sequence_key=sequence_key, step_index=idx)

			self._record_history(sequence_key=sequence_key, step_index=idx, status="EXECUTING")
			# Placeholder: actuate valve here (open/close).
			# TODO: integrate with real hardware valve command.

			if step.time_delay_s > 0:
				# Placeholder timing behavior: delay after step completes.
				time.sleep(step.time_delay_s)

			self._record_history(sequence_key=sequence_key, step_index=idx, status="COMPLETED")

		self._set_current_step(None)
		# Return to IDLE after sequence completion.
		self._set_system_state("IDLE")
		with self._lock:
			self._active_sequence = "idle"

	def loop_forever(self) -> None:
		"""Consume high-level commands (fill/fire) and run sequences."""
		while True:
			cmd = self._command_queue.get()
			try:
				# Commands come from the Socket.IO handler (`gui_command`) which enqueues
				# raw strings onto `command_queue`.
				if cmd == "fill":
					self._run_sequence("fill")
				elif cmd == "fire":
					self._run_sequence("fire")
				else:
					# Ignore unknown commands.
					pass
			finally:
				try:
					self._command_queue.task_done()
				except Exception:
					pass
