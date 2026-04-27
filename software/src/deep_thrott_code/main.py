from __future__ import annotations

from typing import TYPE_CHECKING

import os
import queue
import threading
import time



if TYPE_CHECKING:
	# These imports are ONLY for IDE/type hints.
	# We keep this main skeleton “light” and not runnable yet.
	from queue import Queue

	from deep_thrott_code.daq.services.sample import RawSample, Sample
	from deep_thrott_code.daq.services.state_store import StateStore


# ---------------------------------------------------------------------
# CPU pinning notes (Raspberry Pi / Linux)
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# Main outline
# ---------------------------------------------------------------------


def main() -> None:
	"""Outline

		This function will:

		1) Create shared objects:
				 - stop_event
				 - sensor_state_store (existing StateStore)
				 - system_state_store
				 - queues: sample_queue, gui_queue, command_queue

		2) Configure “mode” (simulation vs hardware):
				 - build_sensors(simulation=...)
				 - build_sensor_map(...)

		3) Start threads:
				 - DAQ producer thread
				 - DAQ consumer thread
				 - Throttle loop thread
				 - F3 loop thread
				 - GUI thread

		4) Handle shutdown:
				 - Ctrl+C sets stop_event
				 - join threads
				 - close CSV logger
	"""

	# -----------------------------------------------------------------
	# 1) Start DAQ
	# -----------------------------------------------------------------

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
	# throttle_thread = threading.Thread(...)
	# throttle_thread.start()

	# -----------------------------------------------------------------
	# 3) F3 loop (TODO)
	# -----------------------------------------------------------------
	#
	# def f3_entrypoint() -> None:
	#     pin_current_thread_to_cpu(CPU_CORE_4_DAQ_CONSUMER_AND_F3)
	#     f3_loop_placeholder()

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
	main()

