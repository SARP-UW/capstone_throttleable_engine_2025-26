import logging
import threading
import time
from queue import Empty


_log = logging.getLogger(__name__)


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

    # If any sensor specifies a sampling rate, we can pace based on the next
    # scheduled due time instead of a fixed loop dt. This avoids pathological
    # behavior on platforms with coarse sleep granularity (e.g., ~10-15ms on
    # Windows), where trying to sleep at 1ms can collapse effective rates.
    use_due_scheduler = False
    for _s in sensor_list:
        hz = getattr(_s, "sampling_rate_hz", None)
        if hz is None:
            continue
        try:
            if float(hz) > 0:
                use_due_scheduler = True
                break
        except Exception:
            continue

    # Optional per-sensor sampling schedule.
    # If a sensor instance defines `sampling_rate_hz`, we only read it when due.
    next_due_t: dict[str, float] = {}

    # Rate-limit timeout logs per sensor name so we don't spam.
    last_timeout_log_t: dict[str, float] = {}
    timeout_log_period_s = 5.0

    while not stop_event.is_set():
        t_start = time.perf_counter()

        now = t_start

        enqueued = 0

        for sensor in sensor_list:
            name = getattr(sensor, "name", None)
            sensor_name = str(name) if name else sensor.__class__.__name__

            sampling_rate_hz = getattr(sensor, "sampling_rate_hz", None)
            if sampling_rate_hz is not None:
                try:
                    hz = float(sampling_rate_hz)
                except Exception:
                    hz = 0.0

                if hz > 0:
                    period_s = 1.0 / hz
                    due = next_due_t.get(sensor_name)
                    if due is None:
                        next_due_t[sensor_name] = now
                    elif now < due:
                        continue

            try:
                sample = sensor.read_raw_sample()
            except TimeoutError:
                # Treat ADC DRDY timeouts as a dropped sample for this cycle.
                # Keep the producer loop alive so other channels can continue.
                now = time.monotonic()
                last = last_timeout_log_t.get(sensor_name, 0.0)
                if (now - last) >= timeout_log_period_s:
                    _log.warning("DAQ read timeout (dropping sample): %s", sensor_name)
                    last_timeout_log_t[sensor_name] = now

                # Back off until next period (if configured) so we don't hammer a failing channel.
                if sampling_rate_hz is not None:
                    try:
                        hz = float(sampling_rate_hz)
                    except Exception:
                        hz = 0.0
                    if hz > 0:
                        next_due_t[sensor_name] = time.perf_counter() + (1.0 / hz)
                continue

            if sampling_rate_hz is not None:
                try:
                    hz = float(sampling_rate_hz)
                except Exception:
                    hz = 0.0
                if hz > 0:
                    # Schedule from *now* to avoid backlog catch-up storms.
                    next_due_t[sensor_name] = time.perf_counter() + (1.0 / hz)

            sample_queue.put(sample)
            enqueued += 1

        t_end = time.perf_counter()
        elapsed = t_end - t_start

        sleep_requested = 0.0
        sleep_actual = 0.0
        sleep_overshoot = 0.0
        overrun = 0

        if pace:
            if use_due_scheduler and next_due_t:
                try:
                    next_due = min(next_due_t.values())
                except Exception:
                    next_due = None
                if next_due is not None:
                    sleep_requested = next_due - time.perf_counter()
            elif dt > 0:
                sleep_requested = dt - elapsed

            if sleep_requested > 0:
                t_sleep_start = time.perf_counter()
                time.sleep(sleep_requested)
                t_sleep_end = time.perf_counter()
                sleep_actual = t_sleep_end - t_sleep_start
                sleep_overshoot = sleep_actual - sleep_requested
            else:
                sleep_requested = 0.0
                overrun = 1 if (dt > 0 and not use_due_scheduler) else 0

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
