"""Backend-side handler for GUI control commands.

Consumes control messages coming from the GUI (via Socket.IO) and calls into
callbacks provided by the composition root (`deep_thrott_code/main.py`).

This is separate from the sequencing runtime:
- `control_queue` -> start/stop logging, toggle simulation mode, etc.
- `command_queue` -> sequence commands ("fill"/"fire") handled by the F3C Controller
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable


class GuiCommandHandler:
	"""Handles GUI control messages from `control_queue`."""

	def __init__(
		self,
		*,
		control_queue: queue.Queue,
		emit_system: Callable[[str], None],
		start_log: Callable[[bool], None],
		stop_log: Callable[[], None],
		is_running: Callable[[], bool],
	) -> None:
		self._control_queue = control_queue
		self._emit_system = emit_system
		self._start_log = start_log
		self._stop_log = stop_log
		self._is_running = is_running

		self._lock = threading.Lock()
		# "Simulation Mode" is a latched setting that applies to the next Start Log.
		self._simulation_enabled = True

	def _emit(self, text: str) -> None:
		try:
			self._emit_system(text)
		except Exception:
			pass

	def set_simulation_enabled(self, enabled: bool) -> None:
		"""Update simulation mode state.

		If DAQ is running, this only affects the *next* `start_log`.
		"""

		enabled_bool = bool(enabled)
		with self._lock:
			self._simulation_enabled = enabled_bool
			running = self._is_running()

		if running:
			self._emit("Simulation Mode updated; takes effect next Start Log.")
		else:
			self._emit(f"Simulation Mode set to {'ON' if enabled_bool else 'OFF'}.")

	def command_loop_forever(self) -> None:
		"""Consume `control_queue` messages forever.

		This loop runs on a dedicated thread started by `main.py`.
		"""

		while True:
			payload = self._control_queue.get()
			try:
				if not isinstance(payload, dict):
					self._emit("Ignored non-object command payload.")
					continue

				name = payload.get("name")
				if name == "set_simulation":
					self.set_simulation_enabled(bool(payload.get("enabled")))
				elif name == "start_log":
					with self._lock:
						simulation = bool(self._simulation_enabled)
					self._start_log(simulation)
				elif name == "stop_log":
					self._stop_log()
				else:
					self._emit(f"Unknown command: {name}")
			finally:
				try:
					self._control_queue.task_done()
				except Exception:
					pass


# Backward-compatible alias: older code imported BackendController.
BackendController = GuiCommandHandler


__all__ = ["GuiCommandHandler", "BackendController"]
