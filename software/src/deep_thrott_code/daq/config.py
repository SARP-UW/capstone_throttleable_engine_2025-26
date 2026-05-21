
# This module intentionally contains lightweight runtime configuration knobs.
# It is imported by both sensor implementations and the DAQ runtime.


# If True, discard the first conversion after each input MUX change.
# This improves settling behavior when scanning multiple channels.
ADC_SETTLE_DISCARD: bool = True


# If True, force ADS124S08 DATARATE.DR to max (4000 SPS) at startup.
# This maximizes scan throughput when multiplexing channels.
ADC_FORCE_MAX_DATARATE: bool = False


# Optional producer rate instrumentation.
DAQ_EMIT_RATE_STATS: bool = False
DAQ_RATE_STATS_PERIOD_S: float = 5.0


# Producer loop pacing.
#
# The producer loop iterates quickly and only reads a sensor when it is "due"
# (based on that sensor's `sampling_rate_hz`). The loop itself should run
# significantly faster than the fastest sensor rate so reads get naturally
# staggered across time instead of all landing on the same tick.
#
# - If DAQ_PRODUCER_LOOP_HZ is set (not None), it is used directly.
# - Otherwise, loop_hz is computed as:
#     min(DAQ_PRODUCER_LOOP_HZ_MAX, max_sensor_hz * DAQ_PRODUCER_SCHED_MULT)
#
DAQ_PRODUCER_LOOP_HZ: float | None = None
DAQ_PRODUCER_SCHED_MULT: float = 10.0
DAQ_PRODUCER_LOOP_HZ_MAX: float = 2000.0

