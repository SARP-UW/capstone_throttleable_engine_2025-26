
# This module intentionally contains lightweight runtime configuration knobs.
# It is imported by both sensor implementations and the DAQ runtime.


# If True, discard the first conversion after each input MUX change.
# This improves settling behavior when scanning multiple channels.
ADC_SETTLE_DISCARD: bool = True


# If True, force ADS124S08 DATARATE.DR to max (4000 SPS) at startup.
# This maximizes scan throughput when multiplexing channels.
ADC_FORCE_MAX_DATARATE: bool = False


# When DATARATE is selected automatically from the configured sensor rates,
# reserve extra headroom above the theoretical minimum conversion rate.
# This accounts for SPI command overhead, MUX changes, and scheduling jitter.
ADC_DATARATE_HEADROOM: float = 1.5


# Optional producer rate instrumentation.
DAQ_EMIT_RATE_STATS: bool = True
DAQ_RATE_STATS_PERIOD_S: float = 5.0


# Internally oversubscribe per-sensor sampling targets to compensate for
# scheduler jitter and conversion overhead. A configured sensor rate in
# hardware.yml is multiplied by this value for producer scheduling and ADC
# datarate sizing.
DAQ_SENSOR_RATE_TARGET_MULT: float = 1.0


# Number of recent sample timestamps used to estimate achieved per-sensor rate
# for the GUI.
DAQ_SENSOR_RATE_ESTIMATE_WINDOW: int = 12


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
DAQ_PRODUCER_SCHED_MULT: float = 20.0
DAQ_PRODUCER_LOOP_HZ_MAX: float = 4000.0

