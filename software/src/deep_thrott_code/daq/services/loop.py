import threading
import time
from queue import Empty


class ProducerStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.cycles = 0
        self.samples_enqueued = 0
        self.busy_s = 0.0
        self.sleep_requested_s = 0.0
        self.sleep_actual_s = 0.0
        self.sleep_overshoot_s = 0.0
        self.overruns = 0

    def update(
        self,
        *,
        cycles: int,
        samples: int,
        busy_s: float,
        sleep_requested_s: float,
        sleep_actual_s: float,
        sleep_overshoot_s: float,
        overruns: int,
    ) -> None:
        with self._lock:
            self.cycles += cycles
            self.samples_enqueued += samples
            self.busy_s += busy_s
            self.sleep_requested_s += sleep_requested_s
            self.sleep_actual_s += sleep_actual_s
            self.sleep_overshoot_s += sleep_overshoot_s
            self.overruns += overruns

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "cycles": float(self.cycles),
                "samples_enqueued": float(self.samples_enqueued),
                "busy_s": float(self.busy_s),
                "sleep_requested_s": float(self.sleep_requested_s),
                "sleep_actual_s": float(self.sleep_actual_s),
                "sleep_overshoot_s": float(self.sleep_overshoot_s),
                "overruns": float(self.overruns),
            }


def producer_loop(
    sensor_list,
    sample_queue,
    stop_event,
    loop_hz: float,
    stats: ProducerStats | None = None,
    *,
    pace: bool = True,
):
    dt = (1.0 / loop_hz) if pace and loop_hz > 0 else 0.0

    while not stop_event.is_set():
        t_start = time.perf_counter()

        enqueued = 0

        for sensor in sensor_list:
            try:
                sample = sensor.read_raw_sample()
            except TimeoutError:
                # Treat ADC DRDY timeouts as a dropped sample for this cycle.
                # Keep the producer loop alive so other channels can continue.
                continue

            sample_queue.put(sample)
            enqueued += 1

        t_end = time.perf_counter()
        elapsed = t_end - t_start

        if pace and dt > 0:
            sleep_requested = dt - elapsed
            if sleep_requested > 0:
                t_sleep_start = time.perf_counter()
                time.sleep(sleep_requested)
                t_sleep_end = time.perf_counter()
                sleep_actual = t_sleep_end - t_sleep_start
                sleep_overshoot = sleep_actual - sleep_requested
                overrun = 0
            else:
                sleep_requested = 0.0
                sleep_actual = 0.0
                sleep_overshoot = 0.0
                overrun = 1
        else:
            sleep_requested = 0.0
            sleep_actual = 0.0
            sleep_overshoot = 0.0
            overrun = 0

        if stats is not None:
            stats.update(
                cycles=1,
                samples=enqueued,
                busy_s=elapsed,
                sleep_requested_s=sleep_requested,
                sleep_actual_s=sleep_actual,
                sleep_overshoot_s=sleep_overshoot,
                overruns=overrun,
            )


def consumer_loop(sample_queue, gui_queue, store_state, logger, stop_event, sensor_map):
    while not stop_event.is_set():
        batch = []
        try:
            first = sample_queue.get(timeout=0.1)
            batch.append(first)
            sample_queue.task_done()

            while True:
                item = sample_queue.get_nowait()
                batch.append(item)
                sample_queue.task_done()

        except Empty:
            if not batch:
                continue

        processed_samples = []

        for raw_sample in batch:
            sensor = sensor_map[raw_sample.sensor_name]
            sample = sensor.convert_raw_sample_to_sample(raw_sample)
            processed_samples.append(sample)

        for sample in processed_samples:
            store_state.update_sample(sample)
            gui_queue.put(sample)
            logger.write(sample)
