from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict

from .services.loop import ProducerStats, consumer_loop, producer_loop
from .services.logger import CsvLogger
from .services.state_store import StateStore
from .sensors.sensors import build_sensor_map, build_sensors


class CountingLogger:
    def __init__(self, inner: CsvLogger):
        self._inner = inner
        self._lock = threading.Lock()
        self.samples_total = 0
        self.samples_by_sensor: dict[str, int] = defaultdict(int)
        self.status_error_count = 0
        self.status_non_ok_count = 0
        self.monotonic_violations = 0
        self._last_t_mono_by_sensor: dict[str, float] = {}

    def write(self, sample) -> None:
        # Write first so logging failures still surface.
        self._inner.write(sample)

        with self._lock:
            self.samples_total += 1
            self.samples_by_sensor[sample.sensor_name] += 1

            status = getattr(sample, "status", "")
            if status and status != "OK":
                self.status_non_ok_count += 1
            if str(status).upper() == "ERROR":
                self.status_error_count += 1

            last = self._last_t_mono_by_sensor.get(sample.sensor_name)
            if last is not None and sample.t_monotonic < last:
                self.monotonic_violations += 1
            self._last_t_mono_by_sensor[sample.sensor_name] = sample.t_monotonic

    def close(self) -> None:
        self._inner.close()


def main(
    *,
    duration_s: float = 10.0,
    loop_hz: float = 700.0,
    log_path: str = "daq_test_log.csv",
    fsync_every_flush: bool = True,
    pace_producer: bool = True,
    min_rate_ratio: float = 0.90,
    max_queue_ratio: float = 0.90,
) -> int:
    sample_queue: queue.Queue = queue.Queue(maxsize=1000)
    gui_queue: queue.Queue = queue.Queue(maxsize=1000)
    stop_event = threading.Event()
    state_store = StateStore()

    sensors = build_sensors()
    sensor_map = build_sensor_map(sensors)
    expected_names = [s.name for s in sensors]

    raw_logger = CsvLogger(log_path, flush_every=25, fsync_every_flush=fsync_every_flush)
    logger = CountingLogger(raw_logger)

    producer_stats = ProducerStats()

    producer_thread = threading.Thread(
        target=producer_loop,
        args=(sensors, sample_queue, stop_event, float(loop_hz), producer_stats),
        kwargs={"pace": bool(pace_producer)},
        daemon=True,
        name="producer",
    )

    consumer_thread = threading.Thread(
        target=consumer_loop,
        args=(sample_queue, gui_queue, state_store, logger, stop_event, sensor_map),
        daemon=True,
        name="consumer",
    )

    producer_thread.start()
    consumer_thread.start()

    t_start = time.perf_counter()
    t_end = t_start + float(duration_s)
    next_print = t_start
    max_qsize = 0
    t_stop: float | None = None

    try:
        while time.perf_counter() < t_end:
            now = time.perf_counter()
            qsize = sample_queue.qsize()
            if qsize > max_qsize:
                max_qsize = qsize

            if now >= next_print:
                snap = state_store.snapshot()
                missing = [n for n in expected_names if n not in snap]

                if missing:
                    print(f"waiting for samples... missing={missing} qsize={qsize}")
                else:
                    parts = []
                    for name in expected_names:
                        s = snap[name]
                        parts.append(f"{name}={s.value:.3f} {s.units}")
                    print(" | ".join(parts) + f" | qsize={qsize}")

                next_print = now + 1.0

            time.sleep(0.01)

        t_stop = time.perf_counter()

    finally:
        if t_stop is None:
            t_stop = time.perf_counter()
        stop_event.set()
        producer_thread.join(timeout=2.0)
        consumer_thread.join(timeout=2.0)
        logger.close()

    t_done = time.perf_counter()
    duration_run = t_stop - t_start
    duration_shutdown = t_done - t_stop

    # --- Success criteria ---
    expected_total_rate = float(loop_hz) * len(expected_names)
    achieved_total_rate = (logger.samples_total / duration_run) if duration_run > 0 else 0.0
    rate_ratio = (achieved_total_rate / expected_total_rate) if expected_total_rate > 0 else 0.0

    final = state_store.snapshot()
    missing_final = [n for n in expected_names if n not in final]

    fail_reasons: list[str] = []
    if missing_final:
        fail_reasons.append(f"missing_samples_for={missing_final}")

    if logger.status_error_count:
        fail_reasons.append(f"status_error_count={logger.status_error_count}")

    if rate_ratio < float(min_rate_ratio):
        fail_reasons.append(
            f"throughput_low achieved={achieved_total_rate:.1f}/s expected={expected_total_rate:.1f}/s ratio={rate_ratio:.3f}"
        )

    if sample_queue.maxsize and max_qsize > int(sample_queue.maxsize * float(max_queue_ratio)):
        fail_reasons.append(f"queue_backlog max_qsize={max_qsize} maxsize={sample_queue.maxsize}")

    if logger.monotonic_violations:
        fail_reasons.append(f"monotonic_violations={logger.monotonic_violations}")

    passed = not fail_reasons

    # --- Report ---
    print("\n=== DAQ TEST REPORT ===")
    print(f"duration_run_s={duration_run:.3f}")
    print(f"duration_shutdown_s={duration_shutdown:.3f}")
    print(f"loop_hz_target={float(loop_hz):.2f}")
    print(f"sensors={expected_names}")
    producer = producer_stats.snapshot()
    producer_cycles = int(producer["cycles"])
    producer_samples = int(producer["samples_enqueued"])
    producer_busy_s = float(producer["busy_s"])
    producer_sleep_requested_s = float(producer["sleep_requested_s"])
    producer_sleep_actual_s = float(producer["sleep_actual_s"])
    producer_sleep_overshoot_s = float(producer["sleep_overshoot_s"])
    producer_overruns = int(producer["overruns"])

    producer_cycle_rate = (producer_cycles / duration_run) if duration_run > 0 else 0.0
    producer_sample_rate = (producer_samples / duration_run) if duration_run > 0 else 0.0
    avg_sleep_overshoot_us = (
        (producer_sleep_overshoot_s / producer_cycles) * 1_000_000 if producer_cycles > 0 else 0.0
    )

    print(f"samples_written_total={logger.samples_total}")
    print(f"samples_written_by_sensor={dict(logger.samples_by_sensor)}")
    print(f"expected_total_rate={expected_total_rate:.2f}/s")
    print(f"achieved_total_rate={achieved_total_rate:.2f}/s")
    print(f"rate_ratio={rate_ratio:.3f}")
    print(f"max_queue_size_seen={max_qsize}")
    print(f"producer_cycles={producer_cycles}")
    print(f"producer_cycle_rate={producer_cycle_rate:.2f}/s")
    print(f"producer_samples_enqueued={producer_samples}")
    print(f"producer_sample_rate={producer_sample_rate:.2f}/s")
    print(f"producer_busy_s={producer_busy_s:.3f}")
    print(f"producer_sleep_requested_s={producer_sleep_requested_s:.3f}")
    print(f"producer_sleep_actual_s={producer_sleep_actual_s:.3f}")
    print(f"producer_sleep_overshoot_s={producer_sleep_overshoot_s:.3f}")
    print(f"producer_avg_sleep_overshoot_us={avg_sleep_overshoot_us:.1f}")
    print(f"producer_overruns={producer_overruns}")
    print(f"status_non_ok_count={logger.status_non_ok_count}")
    print(f"status_error_count={logger.status_error_count}")
    print(f"monotonic_violations={logger.monotonic_violations}")
    print(f"log_path={log_path}")

    if passed:
        print("RESULT=PASS")
        return 0

    print("RESULT=FAIL")
    for r in fail_reasons:
        print(f"- {r}")
    return 2


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-s", type=float, default=10.0)
    parser.add_argument("--loop-hz", type=float, default=700.0)
    parser.add_argument("--log-path", type=str, default="daq_test_log.csv")
    parser.add_argument("--no-fsync", action="store_true")
    parser.add_argument("--no-pace", action="store_true")
    args = parser.parse_args()

    raise SystemExit(
        main(
            duration_s=args.duration_s,
            loop_hz=args.loop_hz,
            log_path=args.log_path,
            fsync_every_flush=not args.no_fsync,
            pace_producer=not args.no_pace,
        )
    )

