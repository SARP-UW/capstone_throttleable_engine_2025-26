"""DAQ runtime lifecycle helpers (threads, queues, logging)."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable


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

		from datetime import datetime
		from pathlib import Path

		now = datetime.now()
		folder_date = now.strftime("%Y/%m/%d") 
		file_timestamp = now.strftime("%H-%M-%S_data.csv")
		base_dir = Path("logs")
		full_path = base_dir / folder_date / file_timestamp
		full_path.parent.mkdir(parents=True, exist_ok=True)

		self._log_path = str(full_path)

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

	def start(self, simulation: bool, test_name: str | None = None) -> None:
		"""Start DAQ threads and begin emitting samples to `gui_queue`."""

		import time

		from deep_thrott_code.daq import config as daq_config  # noqa: PLC0415
		from deep_thrott_code.daq.services.loop import ProducerStats, consumer_loop, producer_loop  # noqa: PLC0415
		from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
		from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
		from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415

		with self._lock:
			if self._running:
				self._emit_system("Log already running.")
				return

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
		logger = CsvLogger(self._log_path, header, flush_every=25, fsync_every_flush=False)
		producer_stats = ProducerStats()

		self._drain_queue(self._sample_queue)
		self._drain_queue(self._gui_queue)

		def producer_entrypoint() -> None:
			self._pin_thread_to_cpu(self._producer_cpu)
			producer_loop(sensors, self._sample_queue, stop_event, 100.0, stats=producer_stats)

		def consumer_entrypoint() -> None:
			self._pin_thread_to_cpu(self._consumer_cpu)
			consumer_loop(self._sample_queue, self._gui_queue, state_store, logger, stop_event, sensor_map)

		producer_thread = threading.Thread(target=producer_entrypoint, daemon=True, name="producer")
		consumer_thread = threading.Thread(target=consumer_entrypoint, daemon=True, name="consumer")

		# Optional DAQ rate monitor thread. Delete after testing 
		monitor_thread: threading.Thread | None = None
		if bool(getattr(daq_config, "DAQ_EMIT_RATE_STATS", False)):
			period_s = float(getattr(daq_config, "DAQ_RATE_STATS_PERIOD_S", 5.0) or 5.0)

			def monitor_entrypoint() -> None:
				last = producer_stats.snapshot()
				last_t = time.perf_counter()
				while not stop_event.is_set():
					time.sleep(period_s)
					now = time.perf_counter()
					snap = producer_stats.snapshot()
					dt = now - last_t
					if dt <= 0:
						last = snap
						last_t = now
						continue
					cycles = snap["cycles"] - last["cycles"]
					samples = snap["samples_enqueued"] - last["samples_enqueued"]
					overruns = snap["overruns"] - last["overruns"]
					busy = snap["busy_s"] - last["busy_s"]
					self._emit_system(
						f"DAQ rate: {cycles / dt:.1f} cycles/s, {samples / dt:.1f} samples/s, busy={busy / dt:.0%}, overruns={int(overruns)}"
					)
					last = snap
					last_t = now

			monitor_thread = threading.Thread(target=monitor_entrypoint, daemon=True, name="producer_monitor")
		# Delete until here

		producer_thread.start()
		consumer_thread.start()
		if monitor_thread is not None:
			monitor_thread.start()

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


__all__ = ["DaqRuntime", "drain_queue", "emit_system"]
