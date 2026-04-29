from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StepDef:
	valve: str
	action: str
	time_delay_s: float
	user_input: bool
	condition_valve: str | None
	condition_state: str | None
	system_state: str


@dataclass(frozen=True)
class SequenceDef:
	name: str
	steps: list[StepDef]


def _as_str_or_none(v: Any) -> str | None:  # noqa: ANN401
	if v is None:
		return None
	if isinstance(v, str):
		return v
	return str(v)


def load_sequences_yaml(path: str | Path) -> dict[str, SequenceDef]:
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
		self._sequences = dict(sequences)
		self._command_queue = command_queue
		self._f3_to_gui_queue = f3_to_gui_queue
		self._gui_to_f3_queue = gui_to_f3_queue

		self._lock = threading.Lock()
		self._system_state = "IDLE"
		self._active_sequence: str = "idle"
		self._current_step_index: int | None = None
		self._history: list[dict[str, Any]] = []
		self._waiting_manual: dict[str, Any] | None = None

	def get_sequence_defs_for_gui(self) -> list[dict[str, Any]]:
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
		with self._lock:
			return {
				"system_state": str(self._system_state),
				"active_sequence": str(self._active_sequence),
				"current_step_index": self._current_step_index,
				"history": list(self._history),
				"waiting_manual": dict(self._waiting_manual) if self._waiting_manual else None,
			}

	def _set_active(self, sequence_key: str) -> None:
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
		seq = self._sequences.get(sequence_key)
		if not seq:
			return

		self._set_active(sequence_key)

		for idx, step in enumerate(seq.steps):
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
				time.sleep(step.time_delay_s)

			self._record_history(sequence_key=sequence_key, step_index=idx, status="COMPLETED")

		self._set_current_step(None)
		self._set_system_state("IDLE")		# return to IDLE after sequence
		with self._lock:
			self._active_sequence = "idle"

	def loop_forever(self) -> None:
		"""Consume high-level commands (fill/fire) and run sequences."""
		while True:
			cmd = self._command_queue.get()
			try:
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
