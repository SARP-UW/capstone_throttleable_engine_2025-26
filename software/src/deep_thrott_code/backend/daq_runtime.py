"""DAQ runtime lifecycle helpers (threads, queues, logging)."""

from __future__ import annotations

import math
import queue
import threading
from collections.abc import Callable


def _build_log_path() -> str:
	from datetime import datetime
	from pathlib import Path

	now = datetime.now()
	folder_date = now.strftime("%Y/%m/%d")
	file_timestamp = now.strftime("%H-%M-%S_data.csv")
	software_dir = Path(__file__).resolve().parents[3]
	base_dir = software_dir / "logs" / "daq"
	full_path = base_dir / folder_date / file_timestamp
	full_path.parent.mkdir(parents=True, exist_ok=True)
	try:
		return str(full_path.resolve())
	except Exception:
		return str(full_path)


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
		producer_cpus: tuple[int, ...] | None = None,
		consumer_cpu: int,
		log_path: str = "daq_backend_log.csv",
	) -> None:
		self._gui_queue = gui_queue
		self._sample_queue = sample_queue

		self._emit_system = emit_system_fn
		self._drain_queue = drain_queue_fn
		self._pin_thread_to_cpu = pin_thread_to_cpu

		self._producer_cpu = int(producer_cpu)
		self._producer_cpus = tuple(int(cpu) for cpu in producer_cpus) if producer_cpus else (int(producer_cpu),)
		self._consumer_cpu = int(consumer_cpu)

		self._log_path = _build_log_path()
		self._log_started_at_wall: float | None = None

		self._lock = threading.Lock()
		self._running = False
		self._stop_event: threading.Event | None = None
		self._producer_threads: list[threading.Thread] = []
		self._consumer_thread: threading.Thread | None = None
		self._logger = None
		self._state_store = None
		self._sensors: list[object] = []
		self._sensor_map: dict[str, object] = {}

	def snapshot_meta(self) -> dict[str, object]:
		"""Return backend/runtime metadata for the GUI."""

		from pathlib import Path

		with self._lock:
			log_path = str(self._log_path)
			try:
				log_dir = str(Path(log_path).parent)
			except Exception:
				log_dir = ""
			return {
				"is_logging": bool(self._running),
				"log_path": log_path,
				"log_dir": log_dir,
				"log_started_at_wall": float(self._log_started_at_wall) if self._log_started_at_wall else None,
			}

	def is_running(self) -> bool:
		with self._lock:
			return bool(self._running)

	@staticmethod
	def _coerce_finite_float(value: object) -> float | None:
		try:
			result = float(value)
		except Exception:
			return None
		return result if math.isfinite(result) else None

	@staticmethod
	def _solve_zero_v_min(*, current_voltage: float, v_max: float, output_min: float, output_max: float, subtractive_offset: float) -> float:
		output_span = float(output_max) - float(output_min)
		if abs(output_span) < 1e-12:
			raise ValueError("output span is zero")

		fraction = (float(subtractive_offset) - float(output_min)) / output_span
		denom = 1.0 - fraction
		if abs(denom) < 1e-12:
			raise ValueError("zero target collapses calibration")

		new_v_min = (float(current_voltage) - fraction * float(v_max)) / denom
		if not math.isfinite(new_v_min):
			raise ValueError("computed v_min is not finite")
		if not new_v_min < float(v_max):
			raise ValueError("computed v_min would collapse voltage span")
		return new_v_min

	def zero_sensor(self, sensor_name: str, current_value: object = None, current_voltage: object = None) -> str:
		sensor_key = str(sensor_name or "").strip()
		if not sensor_key:
			return "Zero failed: missing sensor name."

		with self._lock:
			sensor = self._sensor_map.get(sensor_key)

		if sensor is None:
			return f"Zero failed: sensor '{sensor_key}' is not active."

		current_value_f = self._coerce_finite_float(current_value)
		current_voltage_f = self._coerce_finite_float(current_voltage)

		if hasattr(sensor, "offset_n"):
			if current_value_f is None:
				return f"Zero failed for {sensor_key}: current reading unavailable."
			try:
				sensor.offset_n = float(getattr(sensor, "offset_n", 0.0) or 0.0) + current_value_f
			except Exception as exc:
				return f"Zero failed for {sensor_key}: {exc}"
			return f"Zeroed {sensor_key} load cell at {current_value_f:.3f}."

		if hasattr(sensor, "p_min") and hasattr(sensor, "p_max") and hasattr(sensor, "v_min") and hasattr(sensor, "v_max"):
			if current_voltage_f is None:
				return f"Zero failed for {sensor_key}: current voltage unavailable."
			try:
				new_v_min = self._solve_zero_v_min(
					current_voltage=current_voltage_f,
					v_max=float(getattr(sensor, "v_max")),
					output_min=float(getattr(sensor, "p_min", 0.0)),
					output_max=float(getattr(sensor, "p_max", 0.0)),
					subtractive_offset=float(getattr(sensor, "offset_psi", 0.0) or 0.0),
				)
				sensor.v_min = new_v_min
				sensor.v_span = float(sensor.v_max) - float(sensor.v_min)
			except Exception as exc:
				return f"Zero failed for {sensor_key}: {exc}"
			return f"Zeroed {sensor_key} PT using {current_voltage_f:.4f} V."

		if hasattr(sensor, "flow_min") and hasattr(sensor, "flow_max") and hasattr(sensor, "v_min") and hasattr(sensor, "v_max"):
			if current_voltage_f is None:
				return f"Zero failed for {sensor_key}: current voltage unavailable."
			try:
				new_v_min = self._solve_zero_v_min(
					current_voltage=current_voltage_f,
					v_max=float(getattr(sensor, "v_max")),
					output_min=float(getattr(sensor, "flow_min", 0.0)),
					output_max=float(getattr(sensor, "flow_max", 0.0)),
					subtractive_offset=float(getattr(sensor, "offset_flow", 0.0) or 0.0),
				)
				sensor.v_min = new_v_min
				sensor.v_span = float(sensor.v_max) - float(sensor.v_min)
			except Exception as exc:
				return f"Zero failed for {sensor_key}: {exc}"
			return f"Zeroed {sensor_key} flow meter using {current_voltage_f:.4f} V."

		return f"Zero failed: {sensor_key} does not support GUI zeroing."

	def start(self, simulation: bool, test_name: str | None = None) -> None:
		"""Start DAQ threads and begin emitting samples to `gui_queue`."""

		import time

		from deep_thrott_code.daq import config as daq_config  # noqa: PLC0415
		from deep_thrott_code.daq.services.loop import ConsumerStats, ProducerStats, consumer_loop, producer_loop  # noqa: PLC0415
		from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
		from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
		from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415

		with self._lock:
			if self._running:
				self._emit_system("Log already running.")
				return

		# Allocate a fresh log path per start, so the GUI can display
		# the actual active file.
		log_path = _build_log_path()
		start_wall = time.time()
		with self._lock:
			self._log_path = log_path
			self._log_started_at_wall = start_wall

		try:
			sensors = build_sensors(simulation=bool(simulation), test_name=test_name)
		except Exception as e:
			self._emit_system(str(e))
			return

		sensor_map = build_sensor_map(sensors)
		stop_event = threading.Event()
		state_store = StateStore()
		header = [
            "sensor_name",
            "sensor_kind",
            "t_monotonic",
            "t_wall",
            "Voltage 1",
            "Voltage 2",
            "value",
            "units",
            "filtered_value",
            "source",
		]
		logger = CsvLogger(log_path, header, flush_every=25, fsync_every_flush=False)
		producer_stats = ProducerStats()
		consumer_stats = ConsumerStats()

		def _sampling_target_multiplier() -> float:
			try:
				mult = float(getattr(daq_config, "DAQ_SENSOR_RATE_TARGET_MULT", 1.0) or 1.0)
			except Exception:
				mult = 1.0
			return mult if mult > 0 else 1.0

		def _compute_producer_loop_hz(sensor_list) -> float:
			# Prefer an explicit override if present.
			override = getattr(daq_config, "DAQ_PRODUCER_LOOP_HZ", None)
			if override is not None:
				try:
					v = float(override)
					return v if v > 0 else 0.0
				except Exception:
					pass

			max_sensor_hz = 0.0
			rate_mult = _sampling_target_multiplier()
			for sensor in sensor_list:
				hz = getattr(sensor, "sampling_rate_hz", None)
				if hz is None:
					continue
				try:
					hzf = float(hz)
				except Exception:
					continue
				hzf *= rate_mult
				if hzf > max_sensor_hz:
					max_sensor_hz = hzf

			# If nothing specifies sampling_rate_hz, fall back to the historical default.
			if max_sensor_hz <= 0:
				max_sensor_hz = 100.0

			mult = getattr(daq_config, "DAQ_PRODUCER_SCHED_MULT", 10.0)
			try:
				mult_f = float(mult)
			except Exception:
				mult_f = 10.0
			if mult_f <= 0:
				mult_f = 10.0

			max_hz = getattr(daq_config, "DAQ_PRODUCER_LOOP_HZ_MAX", 2000.0)
			try:
				max_hz_f = float(max_hz)
			except Exception:
				max_hz_f = 2000.0
			if max_hz_f <= 0:
				max_hz_f = 2000.0

			loop_hz = max_sensor_hz * mult_f
			if loop_hz > max_hz_f:
				loop_hz = max_hz_f
			return loop_hz

		self._drain_queue(self._sample_queue)
		self._drain_queue(self._gui_queue)

		producer_loop_hz = _compute_producer_loop_hz(sensors)
		try:
			rate_mult = _sampling_target_multiplier()
			self._emit_system(
				f"Producer loop_hz={producer_loop_hz:.1f} (sampling_rate_hz target x{rate_mult:.2f}; see hardware.yml)"
			)
		except Exception:
			pass

		def producer_entrypoint() -> None:
			# Parallelize by ADC so separate ADS124S08 chips can convert concurrently.
			# Without this, a single thread serializes DRDY waits across ADC1/2/3 and
			# total throughput collapses (looks like ~"100 Hz total" instead of 100 Hz/sensor).
			groups: dict[object, list] = {}
			for s in sensors:
				adc = getattr(s, "adc", None)
				key = adc if adc is not None else "__no_adc__"
				groups.setdefault(key, []).append(s)

			def _sensor_state_sort_key(sensor):
				# Minimize ADS124S08 state churn within one ADC by clustering reads that
				# share the same broad acquisition mode.
				if hasattr(sensor, "idac1_ain") and hasattr(sensor, "idac2_ain"):
					mode_rank = 2  # RTD mode: internal ref + IDAC routing.
				elif hasattr(sensor, "sig_minus_ain"):
					mode_rank = 1  # Differential mode, often with higher PGA gain.
				else:
					mode_rank = 0  # Single-ended PT / flow reads.

				try:
					gain = float(getattr(sensor, "adc_gain", 1.0) or 1.0)
				except Exception:
					gain = 1.0

				try:
					rate = float(getattr(sensor, "sampling_rate_hz", 0.0) or 0.0)
				except Exception:
					rate = 0.0

				return (mode_rank, gain, -rate, getattr(sensor, "name", sensor.__class__.__name__))

			def _group_loop(sensor_group, group_loop_hz: float, cpu_index: int) -> None:
				try:
					self._pin_thread_to_cpu(cpu_index)
				except Exception:
					pass
				producer_loop(sensor_group, self._sample_queue, stop_event, group_loop_hz, stats=producer_stats)

			threads: list[threading.Thread] = []
			for group_index, (_key, sensor_group) in enumerate(groups.items()):
				sensor_group = sorted(sensor_group, key=_sensor_state_sort_key)
				group_loop_hz = _compute_producer_loop_hz(sensor_group)
				cpu_index = self._producer_cpus[group_index % len(self._producer_cpus)] if self._producer_cpus else self._producer_cpu
				thr = threading.Thread(
					target=_group_loop,
					args=(sensor_group, group_loop_hz, cpu_index),
					daemon=True,
					name="producer",
				)
				threads.append(thr)

			with self._lock:
				self._producer_threads = threads

			for thr in threads:
				thr.start()

		def consumer_entrypoint() -> None:
			self._pin_thread_to_cpu(self._consumer_cpu)
			consumer_loop(self._sample_queue, self._gui_queue, state_store, logger, stop_event, sensor_map, stats=consumer_stats)

		producer_thread = threading.Thread(target=producer_entrypoint, daemon=True, name="producer_dispatch")
		consumer_thread = threading.Thread(target=consumer_entrypoint, daemon=True, name="consumer")

		producer_thread.start()
		consumer_thread.start()
		if monitor_thread is not None:
			monitor_thread.start()

		with self._lock:
			self._running = True
			self._stop_event = stop_event
			# producer threads are populated by producer_entrypoint once it groups sensors.
			self._consumer_thread = consumer_thread
			self._logger = logger
			self._state_store = state_store
			self._sensors = list(sensors)
			self._sensor_map = dict(sensor_map)

		self._emit_system(f"Backend log started ({'SIM' if simulation else 'ADC'} mode).")

	def stop(self) -> None:
		"""Stop DAQ threads and close the logger (best-effort)."""

		with self._lock:
			if not self._running:
				self._emit_system("No log running.")
				return

			stop_event = self._stop_event
			producer_threads = list(self._producer_threads)
			consumer_thread = self._consumer_thread
			logger = self._logger
			sensors = list(self._sensors)

			self._running = False
			self._stop_event = None
			self._producer_threads = []
			self._consumer_thread = None
			self._logger = None
			self._state_store = None
			self._sensors = []
			self._sensor_map = {}

		if stop_event is not None:
			stop_event.set()
		for thr in producer_threads:
			try:
				thr.join()
			except Exception:
				pass
		if consumer_thread is not None:
			consumer_thread.join()

		try:
			if logger is not None:
				logger.close()
		except Exception:
			pass

		seen_adc_ids: set[int] = set()
		seen_spi_ids: set[int] = set()
		spi_handles: list[object] = []
		for sensor in sensors:
			adc = getattr(sensor, "adc", None)
			if adc is None:
				continue

			adc_obj_id = id(adc)
			if adc_obj_id not in seen_adc_ids:
				seen_adc_ids.add(adc_obj_id)
				enter_command_mode = getattr(adc, "enter_command_mode", None)
				if callable(enter_command_mode):
					try:
						enter_command_mode()
					except Exception:
						pass
				close = getattr(adc, "close", None)
				if callable(close):
					try:
						close()
					except Exception:
						pass

			spi = getattr(adc, "spi", None)
			if spi is None:
				continue
			spi_obj_id = id(spi)
			if spi_obj_id in seen_spi_ids:
				continue
			seen_spi_ids.add(spi_obj_id)
			spi_handles.append(spi)

		for spi in spi_handles:
			close = getattr(spi, "close", None)
			if callable(close):
				try:
					close()
				except Exception:
					pass

		self._drain_queue(self._sample_queue)
		self._drain_queue(self._gui_queue)
		self._emit_system("Backend log stopped.")


__all__ = ["DaqRuntime", "drain_queue", "emit_system"]
