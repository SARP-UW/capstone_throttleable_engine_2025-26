
# This module intentionally contains lightweight runtime configuration knobs.
# It is imported by both sensor implementations and the DAQ runtime.


# If True, discard the first conversion after each input MUX change.
# This improves settling behavior when scanning multiple channels.
ADC_SETTLE_DISCARD: bool = True


# Extra conversions to discard after entering or leaving RTD mode. RTD reads
# change the ADS124S08 reference and IDAC routing, which can leave the next
# conversion on that ADC partially unsettled even after the usual MUX discard.
ADC_EXTRA_SETTLE_DISCARDS_AFTER_RTD_SWITCH: int = 4


# Time to hold RTD mode active before taking the first reading. This gives the
# IDAC/reference path a chance to settle before we touch the MUX.
RTD_MODE_SETTLE_S: float = 0.02


# Number of differential RTD samples to take while RTD mode stays enabled.
# The median of the burst is used as the RTD code.
RTD_DIFF_BURST_SAMPLES: int = 3


# If True, force ADS124S08 DATARATE.DR to max (4000 SPS) at startup.
# This maximizes scan throughput when multiplexing channels.
ADC_FORCE_MAX_DATARATE: bool = False


# When DATARATE is selected automatically from the configured sensor rates,
# reserve extra headroom above the theoretical minimum conversion rate.
# This accounts for SPI command overhead, MUX changes, and scheduling jitter.
ADC_DATARATE_HEADROOM: float = 1.5


# Optional RTD diagnostic logging.
# When enabled, each RTD emits a throttled backend log line with the raw lead
# codes, raw differential code, inferred resistance, and computed temperature.
RTD_DEBUG_LOG: bool = True
RTD_DEBUG_LOG_PERIOD_S: float = 2.0

# Optional ADS124S08 RTD register readback logging.
RTD_DEBUG_REG_READBACK: bool = True


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

