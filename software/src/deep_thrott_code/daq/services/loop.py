import logging
import threading
import time
from queue import Empty, Full

from .. import config as daq_config


_log = logging.getLogger(__name__)


def _enqueue_gui_sample(gui_queue, sample) -> None:
    try:
        gui_queue.put_nowait(sample)
        return
    except Full:
        pass

    # The GUI queue should never throttle DAQ. If it fills, drop one stale
    # sample and try once more so the browser sees recent data without
    # backpressuring the consumer loop.
    try:
        gui_queue.get_nowait()
    except Empty:
        return
    else:
        try:
            gui_queue.task_done()
        except Exception:
            pass

    try:
        gui_queue.put_nowait(sample)
    except Full:
        pass


def _effective_sampling_rate_hz(sensor) -> float:
    sampling_rate_hz = getattr(sensor, "sampling_rate_hz", None)
    if sampling_rate_hz is None:
        return 0.0
    try:
        hz = float(sampling_rate_hz)
    except Exception:
        return 0.0
    if hz <= 0:
        return 0.0
    try:
        mult = float(getattr(daq_config, "DAQ_SENSOR_RATE_TARGET_MULT", 1.0) or 1.0)
    except Exception:
        mult = 1.0
    if mult <= 0:
        mult = 1.0
    return hz * mult


class ProducerStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.cycles = 0
        self.samples_enqueued = 0
        self.samples_read = 0
        self.busy_s = 0.0
        self.read_s = 0.0
        self.sleep_requested_s = 0.0
        self.sleep_actual_s = 0.0
        self.sleep_overshoot_s = 0.0
        self.overruns = 0
        self.due_skips = 0
        self.timeouts = 0

    def update(
        self,
        *,
        cycles: int,
        samples: int,
        samples_read: int,
        busy_s: float,
        read_s: float,
        sleep_requested_s: float,
        sleep_actual_s: float,
        sleep_overshoot_s: float,
        overruns: int,
        due_skips: int,
        timeouts: int,
    ) -> None:
        with self._lock:
            self.cycles += cycles
            self.samples_enqueued += samples
            self.samples_read += samples_read
            self.busy_s += busy_s
            self.read_s += read_s
            self.sleep_requested_s += sleep_requested_s
            self.sleep_actual_s += sleep_actual_s
            self.sleep_overshoot_s += sleep_overshoot_s
            self.overruns += overruns
            self.due_skips += due_skips
            self.timeouts += timeouts

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "cycles": float(self.cycles),
                "samples_enqueued": float(self.samples_enqueued),
                "samples_read": float(self.samples_read),
                "busy_s": float(self.busy_s),
                "read_s": float(self.read_s),
                "sleep_requested_s": float(self.sleep_requested_s),
                "sleep_actual_s": float(self.sleep_actual_s),
                "sleep_overshoot_s": float(self.sleep_overshoot_s),
                "overruns": float(self.overruns),
                "due_skips": float(self.due_skips),
                "timeouts": float(self.timeouts),
            }


class ConsumerStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.batches = 0
        self.samples = 0
        self.convert_s = 0.0
        self.state_gui_s = 0.0
        self.log_s = 0.0

    def update(
        self,
        *,
        batches: int,
        samples: int,
        convert_s: float,
        state_gui_s: float,
        log_s: float,
    ) -> None:
        with self._lock:
            self.batches += batches
            self.samples += samples
            self.convert_s += convert_s
            self.state_gui_s += state_gui_s
            self.log_s += log_s

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "batches": float(self.batches),
                "samples": float(self.samples),
                "convert_s": float(self.convert_s),
                "state_gui_s": float(self.state_gui_s),
                "log_s": float(self.log_s),
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
        if _effective_sampling_rate_hz(_s) > 0:
            use_due_scheduler = True
            break

    # Optional per-sensor sampling schedule.
    # If a sensor instance defines `sampling_rate_hz`, we only read it when due.
    next_due_t: dict[str, float] = {}

    # Rate-limit timeout logs per sensor name so we don't spam.
    last_timeout_log_t: dict[str, float] = {}
    timeout_log_period_s = 5.0

    while not stop_event.is_set():
        t_start = time.perf_counter()

        enqueued = 0
        samples_read = 0
        read_elapsed = 0.0
        due_skips = 0
        timeout_count = 0

        for sensor in sensor_list:
            now = time.perf_counter()
            name = getattr(sensor, "name", None)
            sensor_name = str(name) if name else sensor.__class__.__name__

            target_hz = _effective_sampling_rate_hz(sensor)
            if target_hz > 0:
                period_s = 1.0 / target_hz
                due = next_due_t.get(sensor_name)
                if due is None:
                    next_due_t[sensor_name] = now
                elif now < due:
                    due_skips += 1
                    continue

            read_t0 = time.perf_counter()
            try:
                sample = sensor.read_raw_sample()
            except TimeoutError as exc:
                read_elapsed += time.perf_counter() - read_t0
                timeout_count += 1
                # Treat ADC DRDY timeouts as a dropped sample for this cycle.
                # Keep the producer loop alive so other channels can continue.
                now = time.monotonic()
                last = last_timeout_log_t.get(sensor_name, 0.0)
                if (now - last) >= timeout_log_period_s:
                    _log.warning("DAQ read timeout (dropping sample): %s | %s", sensor_name, exc)
                    last_timeout_log_t[sensor_name] = now

                # Back off until next period (if configured) so we don't hammer a failing channel.
                if target_hz > 0:
                    next_due_t[sensor_name] = time.perf_counter() + (1.0 / target_hz)
                continue
            read_elapsed += time.perf_counter() - read_t0
            samples_read += 1

            if target_hz > 0:
                # Schedule from *now* to avoid backlog catch-up storms.
                next_due_t[sensor_name] = time.perf_counter() + period_s

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
                samples_read=samples_read,
                busy_s=elapsed,
                read_s=read_elapsed,
                sleep_requested_s=sleep_requested,
                sleep_actual_s=sleep_actual,
                sleep_overshoot_s=sleep_overshoot,
                overruns=overrun,
                due_skips=due_skips,
                timeouts=timeout_count,
            )


def consumer_loop(sample_queue, gui_queue, store_state, logger, stop_event, sensor_map, stats: ConsumerStats | None = None):
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
        convert_t0 = time.perf_counter()

        for raw_sample in batch:
            sensor = sensor_map[raw_sample.sensor_name]
            sample = sensor.convert_raw_sample_to_sample(raw_sample)
            processed_samples.append(sample)
        convert_elapsed = time.perf_counter() - convert_t0

        state_gui_t0 = time.perf_counter()
        for sample in processed_samples:
            store_state.update_sample(sample)
            _enqueue_gui_sample(gui_queue, sample)
        state_gui_elapsed = time.perf_counter() - state_gui_t0

        log_t0 = time.perf_counter()
        write_many = getattr(logger, "write_many", None)
        if callable(write_many):
            write_many(processed_samples)
        else:
            for sample in processed_samples:
                logger.write(sample)
        log_elapsed = time.perf_counter() - log_t0

        if stats is not None:
            stats.update(
                batches=1,
                samples=len(processed_samples),
                convert_s=convert_elapsed,
                state_gui_s=state_gui_elapsed,
                log_s=log_elapsed,
            )
