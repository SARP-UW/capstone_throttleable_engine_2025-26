import time
from queue import Empty
from collections import defaultdict
from sample import RawSample, Sample

def producer_loop(sensor_list, sample_queue, stop_event, loop_hz: float):
    dt = 1.0 / loop_hz

    while not stop_event.is_set():
        t_start = time.perf_counter()

        for sensor in sensor_list:
            sample = sensor.read_sample()
            sample_queue.put(sample)

        elapsed = time.perf_counter() - t_start
        sleep_time = max(0.0, dt - elapsed)
        time.sleep(sleep_time)


def consumer_loop(sample_queue, state_store, logger, stop_event):
    while not stop_event.is_set():
        batch = []

        # --------------------------
        # Step 1: drain queue
        # --------------------------
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

        # --------------------------
        # Step 2: group by category
        # --------------------------
        grouped = defaultdict(list)
        for raw_sample in batch:
            grouped[raw_sample.conversion_type].append(raw_sample)

        # --------------------------
        # Step 3: process each category
        # --------------------------
        processed_samples = []

        processed_samples.extend(process_pressure_batch(grouped["pressure_voltage"]))
        processed_samples.extend(process_load_cell_batch(grouped["load_cell_bridge"]))
        processed_samples.extend(process_flow_batch(grouped["flow_pulse"]))
        processed_samples.extend(process_rtd_batch(grouped["rtd_ratio"]))

        # --------------------------
        # Step 4: update state/log
        # --------------------------
        for sample in processed_samples:
            state_store.update_sample(sample)
            logger.write(sample)

def process_pressure_batch(raw_samples):
    processed = []

    for raw in raw_samples:
        sensor = SENSOR_MAP[raw.sensor_name]

        code = raw.raw_count
        volts = sensor.code_to_voltage(code)
        pressure = sensor.voltage_to_pressure(volts)

        sample = Sample(
            sensor_name=raw.sensor_name,
            sensor_kind=raw.sensor_kind,
            t_monotonic=raw.t_monotonic,
            t_wall=raw.t_wall,
            raw_value=code,
            value=pressure,
            units="psi",
            status="ok",
            source=raw.source,
        )
        processed.append(sample)

    return processed

def process_load_cell_batch(raw_samples):
    processed = []

    for raw in raw_samples:
        sensor = SENSOR_MAP[raw.sensor_name]

        code = raw.raw_count
        volts = sensor.code_to_voltage(code)
        thrust = sensor.voltage_to_force(volts)

        sample = Sample(
            sensor_name=raw.sensor_name,
            sensor_kind=raw.sensor_kind,
            t_monotonic=raw.t_monotonic,
            t_wall=raw.t_wall,
            raw_value=code,
            value=thrust,
            units="N",
            status="ok",
            source=raw.source,
        )
        processed.append(sample)

    return processed

def process_flow_batch(raw_samples):
    processed = []

    for raw in raw_samples:
        sensor = SENSOR_MAP[raw.sensor_name]

        freq = raw.raw_count
        flow = sensor.frequency_to_flow(freq)

        sample = Sample(
            sensor_name=raw.sensor_name,
            sensor_kind=raw.sensor_kind,
            t_monotonic=raw.t_monotonic,
            t_wall=raw.t_wall,
            raw_value=freq,
            value=flow,
            units="kg/s",
            status="ok",
            source=raw.source,
        )
        processed.append(sample)

    return processed

def process_rtd_batch(raw_samples):
    processed = []

    grouped_by_sensor = defaultdict(list)
    for raw in raw_samples:
        grouped_by_sensor[raw.sensor_name].append(raw)

    for sensor_name, raws in grouped_by_sensor.items():
        sensor = SENSOR_MAP[sensor_name]

        rtd_drop = None
        ref_drop = None

        for raw in raws:
            if raw.measurement_role == "rtd_drop":
                rtd_drop = raw.raw_count
            elif raw.measurement_role == "ref_drop":
                ref_drop = raw.raw_count

        if rtd_drop is None or ref_drop is None:
            continue

        temp_c = sensor.raw_counts_to_temperature(rtd_drop, ref_drop)

        sample = Sample(
            sensor_name=sensor_name,
            sensor_kind="temperature",
            t_monotonic=max(r.t_monotonic for r in raws),
            t_wall=max(r.t_wall for r in raws),
            raw_value=(rtd_drop, ref_drop),
            value=temp_c,
            units="degC",
            status="ok",
            source=raws[0].source,
        )
        processed.append(sample)

    return processed
# filter