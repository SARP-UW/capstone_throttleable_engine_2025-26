from __future__ import annotations

from typing import TYPE_CHECKING

import os
import queue
import threading
import time

from deep_thrott_code.daq.services.system_state import SystemStateStore


if TYPE_CHECKING:
	# These imports are ONLY for IDE/type hints.
	# We keep this main skeleton “light” and not runnable yet.
	from queue import Queue

	from deep_thrott_code.daq.services.sample import RawSample, Sample
	from deep_thrott_code.daq.services.state_store import StateStore


# NOTE on system state location:
#
# SystemState/SystemStateStore live in deep_thrott_code.daq.services.system_state.
#
# Reason: the throttle loop and F3 loop will both need to import these types.
# Keeping them out of main.py keeps main readable.


# ---------------------------------------------------------------------
# CPU pinning notes (Raspberry Pi / Linux)
# ---------------------------------------------------------------------
#
# Your diagram uses “Core 1..4”. Linux uses CPU indices 0..3.
#
# Mapping:
#   Core 1 -> CPU 0
#   Core 2 -> CPU 1
#   Core 3 -> CPU 2
#   Core 4 -> CPU 3
#
# Important: affinity is per-thread on Linux, but you must set it from inside
# the thread you want to pin. The easiest pattern is: call
# pin_current_thread_to_cpu(...) at the top of each thread's entrypoint.

CPU_CORE_1_OS_AND_GUI = 0
CPU_CORE_2_THROTTLE = 1
CPU_CORE_3_DAQ_PRODUCER = 2
CPU_CORE_4_DAQ_CONSUMER_AND_F3 = 3


def pin_current_thread_to_cpu(cpu_index: int) -> None:
	"""Best-effort pinning for the *calling thread* (Linux-only).

	- Raspberry Pi: works.
	- Windows/macOS: safe no-op.
	"""

	try:
		os.sched_setaffinity(0, {int(cpu_index)})
	except Exception:
		return


def throttle_control_loop_placeholder(
	*,
	stop_event: threading.Event,
	sensor_state_store: "StateStore",
	system_state_store: SystemStateStore,
) -> None:
	"""Throttle control loop (placeholder).
	"""
	return


def f3_loop_placeholder(
	*,
	stop_event: threading.Event,
	sensor_state_store: "StateStore",
	system_state_store: SystemStateStore,
) -> None:
	"""F3 / F3C loop (placeholder)
	"""
	return


# ---------------------------------------------------------------------
# “main” outline (still just a skeleton)
# ---------------------------------------------------------------------


def main() -> None:
	"""System orchestrator (outline only).

		When we make this runnable later, this function will:

		1) Create shared objects:
				 - stop_event
				 - sensor_state_store (existing StateStore)
				 - system_state_store (SystemStateStore above)
				 - queues: sample_queue, gui_queue, command_queue

		2) Configure “mode” (simulation vs hardware):
				 - build_sensors(simulation=...)
				 - build_sensor_map(...)

		3) Start threads:
				 - DAQ producer thread
				 - DAQ consumer thread
				 - Throttle loop thread
				 - F3 loop thread
				 - (GUI thread or separate process — you already have run_gui.py)

		4) Handle shutdown:
				 - Ctrl+C sets stop_event
				 - join threads
				 - close CSV logger

		For now, we intentionally do NOT do any of that wiring here to keep review
		manageable.
	"""

	# -----------------------------------------------------------------
	# 1) Start DAQ (real code copied from daq_main)
	# -----------------------------------------------------------------
	# NOTE: This block is intentionally “copy/paste-able” from daq_main.py so it’s
	# easy to compare and keep in sync.

	from deep_thrott_code.daq.services.loop import consumer_loop, producer_loop
	from deep_thrott_code.daq.services.logger import CsvLogger
	from deep_thrott_code.daq.services.state_store import StateStore
	from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors

	simulation = True
	loop_hz = 50.0
	producer_cpu = CPU_CORE_3_DAQ_PRODUCER
	consumer_cpu = CPU_CORE_4_DAQ_CONSUMER_AND_F3

	# Queue sizing copied from daq_main (tune later)
	sample_queue: queue.Queue = queue.Queue(maxsize=1000)
	gui_queue: queue.Queue = queue.Queue(maxsize=100)

	stop_event = threading.Event()
	sensor_state_store = StateStore()
	logger = CsvLogger("daq_log.csv")

	sensors = build_sensors(simulation=simulation)
	sensor_map = build_sensor_map(sensors)

	def daq_producer_entrypoint() -> None:
		# Core 3
		pin_current_thread_to_cpu(producer_cpu)
		producer_loop(sensors, sample_queue, stop_event, loop_hz)

	def daq_consumer_entrypoint() -> None:
		# Core 4
		pin_current_thread_to_cpu(consumer_cpu)
		consumer_loop(sample_queue, gui_queue, sensor_state_store, logger, stop_event, sensor_map)

	daq_producer_thread = threading.Thread(
		target=daq_producer_entrypoint,
		daemon=True,
		name="daq_producer",
	)
	daq_consumer_thread = threading.Thread(
		target=daq_consumer_entrypoint,
		daemon=True,
		name="daq_consumer",
	)

	threads = [daq_producer_thread, daq_consumer_thread]
	for t in threads:
		t.start()

	daq = {
		"threads": threads,
		"stop_event": stop_event,
		"sample_queue": sample_queue,
		"gui_queue": gui_queue,
		"sensor_state_store": sensor_state_store,
		"logger": logger,
	}
	print("DAQ started (from deep_thrott_code.main).")

	# -----------------------------------------------------------------
	# 2) Throttle control loop (TODO)
	# -----------------------------------------------------------------
	# system_state_store = SystemStateStore()
	# throttle_thread = threading.Thread(
	#     target=throttle_control_loop_placeholder,
	#     kwargs={
	#         "stop_event": daq["stop_event"],
	#         "sensor_state_store": daq["sensor_state_store"],
	#         "system_state_store": system_state_store,
	#     },
	#     daemon=True,
	#     name="throttle_control",
	# )
	# throttle_thread.start()

	# -----------------------------------------------------------------
	# 3) F3 loop (TODO)
	# -----------------------------------------------------------------
	# If you want “consumer + F3 share Core 4”, you pin BOTH threads to CPU 3:
	#   - DAQ consumer is pinned in daq_consumer_entrypoint() above
	#   - F3 thread should pin itself at entry
	#
	# def f3_entrypoint() -> None:
	#     pin_current_thread_to_cpu(CPU_CORE_4_DAQ_CONSUMER_AND_F3)
	#     f3_loop_placeholder(
	#         stop_event=daq["stop_event"],
	#         sensor_state_store=daq["sensor_state_store"],
	#         system_state_store=system_state_store,
	#     )
	#
	# f3_thread = threading.Thread(target=f3_entrypoint, daemon=True, name="f3")
	# f3_thread.start()

	try:
		while True:
			time.sleep(1.0)
			snapshot = daq["sensor_state_store"].snapshot()
			if "chamber_pressure" in snapshot:
				pc = snapshot["chamber_pressure"]
				print(f"Pc = {pc.value:.2f} {pc.units} [{pc.status}]")
	except KeyboardInterrupt:
		print("\nStopping DAQ...")
		daq["stop_event"].set()
		for t in daq["threads"]:
			t.join(timeout=2.0)
		daq["logger"].close()
		print("DAQ stopped cleanly.")
		return

	return


if __name__ == "__main__":
	# Runs the DAQ harness (throttle + F3 still TODO).
	main()

