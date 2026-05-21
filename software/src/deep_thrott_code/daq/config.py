
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

