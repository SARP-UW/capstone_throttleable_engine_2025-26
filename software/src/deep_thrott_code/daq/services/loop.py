import time
from queue import Empty
from collections import defaultdict
from sample import RawSample, Sample
from state_store import StateStore

def producer_loop(sensor_list, sample_queue, stop_event, loop_hz: float):
    dt = 1.0 / loop_hz

    while not stop_event.is_set():
        t_start = time.perf_counter()

        for sensor in sensor_list:
            sample = sensor.read_raw_sample()
            sample_queue.put(sample)

        elapsed = time.perf_counter() - t_start
        sleep_time = max(0.0, dt - elapsed)
        time.sleep(sleep_time)


def consumer_loop(sample_queue, store_state, logger, stop_event, sensor_map):
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
            logger.write(sample)
