from __future__ import annotations

import queue
import threading
import time

from .services.loop import consumer_loop, producer_loop
from .services.logger import CsvLogger
from .services.state_store import StateStore
from .sensors.sensors import build_sensor_map, build_sensors


def main(
    *,
    duration_s: float = 10.0,
    loop_hz: float = 50.0,
    log_path: str = "daq_test_log.csv",
    fsync_every_flush: bool = True,
) -> int:
    sample_queue: queue.Queue = queue.Queue(maxsize=1000)
    stop_event = threading.Event()
    state_store = StateStore()

    sensors = build_sensors()
    sensor_map = build_sensor_map(sensors)
    expected_names = [s.name for s in sensors]

    logger = CsvLogger(log_path, flush_every=25, fsync_every_flush=fsync_every_flush)

    producer_thread = threading.Thread(
        target=producer_loop,
        args=(sensors, sample_queue, stop_event, float(loop_hz)),
        daemon=True,
        name="producer",
    )

    consumer_thread = threading.Thread(
        target=consumer_loop,
        args=(sample_queue, state_store, logger, stop_event, sensor_map),
        daemon=True,
        name="consumer",
    )

    producer_thread.start()
    consumer_thread.start()

    t_end = time.perf_counter() + float(duration_s)
    next_print = time.perf_counter()

    try:
        while time.perf_counter() < t_end:
            now = time.perf_counter()
            if now >= next_print:
                snap = state_store.snapshot()
                missing = [n for n in expected_names if n not in snap]

                if missing:
                    print(f"waiting for samples... missing={missing} qsize={sample_queue.qsize()}")
                else:
                    parts = []
                    for name in expected_names:
                        s = snap[name]
                        parts.append(f"{name}={s.value:.3f} {s.units}")
                    print(" | ".join(parts) + f" | qsize={sample_queue.qsize()}")

                next_print = now + 1.0

            time.sleep(0.01)

    finally:
        stop_event.set()
        producer_thread.join(timeout=2.0)
        consumer_thread.join(timeout=2.0)
        logger.close()

    final = state_store.snapshot()
    missing_final = [n for n in expected_names if n not in final]
    if missing_final:
        print(f"ERROR: never received samples for {missing_final}")
        return 2

    print(f"wrote {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

