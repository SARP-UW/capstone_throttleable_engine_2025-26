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
		start_log: Callable[[bool, str | None, list[str] | None], None],
		stop_log: Callable[[], None],
		is_running: Callable[[], bool],
		zero_sensor: Callable[[str, object, object], str] | None = None,
		clear_daq_state: Callable[[], None] | None = None,
	) -> None:
		self._control_queue = control_queue
		self._emit_system = emit_system
		self._start_log = start_log
		self._stop_log = stop_log
		self._is_running = is_running
		self._zero_sensor = zero_sensor
		self._clear_daq_state = clear_daq_state

		self._lock = threading.Lock()
		# "Simulation Mode" is a latched setting that applies to the next Start Log.
		self._simulation_enabled = True
		# "Test" is a latched setting that applies to the next Start Log.
		self._test_name: str | None = "hotfire"
		self._selected_sensor_names: tuple[str, ...] | None = None

	def _available_sensor_names(self, simulation: bool | None = None, test_name: str | None = None) -> list[str]:
		from deep_thrott_code.daq.sensors.sensors import available_sensor_names  # noqa: PLC0415

		if simulation is None or test_name is None:
			with self._lock:
				sim = self._simulation_enabled if simulation is None else bool(simulation)
				test = self._test_name if test_name is None else test_name
		else:
			sim = bool(simulation)
			test = test_name
		return available_sensor_names(simulation=sim, test_name=test)

	def _resolved_selected_sensor_names(self) -> list[str]:
		with self._lock:
			selected = list(self._selected_sensor_names) if self._selected_sensor_names is not None else None
			simulation = bool(self._simulation_enabled)
			test_name = self._test_name

		available = self._available_sensor_names(simulation=simulation, test_name=test_name)
		if selected is None:
			return available
		selected_set = {name for name in selected if name in available}
		return [name for name in available if name in selected_set]

	def snapshot_meta(self) -> dict[str, object]:
		available = self._available_sensor_names()
		selected = self._resolved_selected_sensor_names()
		return {
			"available_sensor_names": available,
			"selected_sensor_names": selected,
			"sensor_selection_locked": bool(self._is_running()),
		}

	def _emit(self, text: str) -> None:
		try:
			self._emit_system(text)
		except Exception:
			pass

	def _clear_latest_daq_state(self) -> None:
		try:
			if callable(self._clear_daq_state):
				self._clear_daq_state()
		except Exception:
			pass

	def set_simulation_enabled(self, enabled: bool) -> None:
		"""Update simulation mode state.

		If DAQ is running, this only affects the *next* `start_log`.
		"""

		enabled_bool = bool(enabled)
		with self._lock:
			self._simulation_enabled = enabled_bool
			if self._selected_sensor_names is not None:
				available = self._available_sensor_names(simulation=enabled_bool, test_name=self._test_name)
				filtered = tuple(name for name in self._selected_sensor_names if name in available)
				self._selected_sensor_names = filtered or None
			running = self._is_running()

		if running:
			self._emit("Simulation Mode updated; takes effect next Start Log.")
		else:
			self._emit(f"Simulation Mode set to {'ON' if enabled_bool else 'OFF'}.")

	def set_test_name(self, test_name: str | None) -> None:
		"""Update test selection.

		If DAQ is running, restart the log to apply immediately.
		"""

		normalized = str(test_name or "").strip().lower()
		if normalized not in {"hotfire", "injector cold flow"}:
			self._emit(f"Ignored unknown test: {test_name}")
			return

		with self._lock:
			self._test_name = normalized
			if self._selected_sensor_names is not None:
				available = self._available_sensor_names(simulation=self._simulation_enabled, test_name=normalized)
				filtered = tuple(name for name in self._selected_sensor_names if name in available)
				self._selected_sensor_names = filtered or None
			simulation = bool(self._simulation_enabled)
			running = self._is_running()

		if not running:
			self._emit(f"Test set to {normalized}.")
			return

		self._emit("Test changed; restarting log to apply.")
		try:
			self._stop_log()
		except Exception:
			pass
		self._clear_latest_daq_state()
		try:
			self._start_log(simulation, normalized, self._resolved_selected_sensor_names())
		except Exception:
			pass

	def set_selected_sensor_names(self, sensor_names: object) -> None:
		if self._is_running():
			self._emit("Sensor selection is locked while logging.")
			return

		available = self._available_sensor_names()
		if isinstance(sensor_names, (list, tuple, set)):
			normalized = []
			seen = set()
			for value in sensor_names:
				name = str(value or "").strip()
				if not name or name in seen or name not in available:
					continue
				seen.add(name)
				normalized.append(name)
		else:
			normalized = []

		with self._lock:
			self._selected_sensor_names = tuple(normalized)

		if normalized:
			self._emit(f"Selected {len(normalized)} sensor(s) for next Start Log.")
		else:
			self._emit("No sensors selected for next Start Log.")

	def zero_sensor(self, sensor_name: str | None, current_value: object = None, current_voltage: object = None) -> None:
		sensor_key = str(sensor_name or "").strip()
		if not sensor_key:
			self._emit("Zero ignored: missing sensor name.")
			return
		if not callable(self._zero_sensor):
			self._emit(f"Zero ignored for {sensor_key}: zero callback not configured.")
			return
		try:
			message = self._zero_sensor(sensor_key, current_value, current_voltage)
		except Exception as exc:
			message = f"Zero failed for {sensor_key}: {exc}"
		self._emit(message)

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
				elif name == "set_test":
					self.set_test_name(payload.get("test"))
				elif name == "start_log":
					with self._lock:
						simulation = bool(self._simulation_enabled)
						test_name = self._test_name
					selected_sensor_names = self._resolved_selected_sensor_names()
					self._clear_latest_daq_state()
					self._start_log(simulation, test_name, selected_sensor_names)
				elif name == "stop_log":
					self._stop_log()
					self._clear_latest_daq_state()
				elif name == "set_sensors":
					self.set_selected_sensor_names(payload.get("sensor_names"))
				elif name == "zero_sensor":
					self.zero_sensor(
						payload.get("sensor_name"),
						payload.get("current_value"),
						payload.get("current_voltage"),
					)
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
