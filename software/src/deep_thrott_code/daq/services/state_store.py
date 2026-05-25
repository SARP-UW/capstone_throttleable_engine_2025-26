import threading
from collections import deque

from .. import config as daq_config
from .sample import Sample

class StateStore:
    def __init__(self):
        self._latest = {}
        try:
            window = int(getattr(daq_config, "DAQ_SENSOR_RATE_ESTIMATE_WINDOW", 12) or 12)
        except Exception:
            window = 12
        if window < 2:
            window = 2
        self._rate_window = window
        self._recent_t_by_sensor = {}
        self._lock = threading.Lock()

    # Consumer calls this to update the latest sample for a sensor
    def update_sample(self, sample: Sample):
        with self._lock:
            recent = self._recent_t_by_sensor.get(sample.sensor_name)
            if recent is None:
                recent = deque(maxlen=self._rate_window)
                self._recent_t_by_sensor[sample.sensor_name] = recent
            recent.append(float(sample.t_monotonic))

            achieved_rate_hz = None
            if len(recent) >= 2:
                span_s = recent[-1] - recent[0]
                if span_s > 0:
                    achieved_rate_hz = (len(recent) - 1) / span_s
            sample.achieved_rate_hz = achieved_rate_hz
            self._latest[sample.sensor_name] = sample

    # call this to get a quick lookup for one sensor's latest sample (for pid / maybe f3)
    def get(self, name: str):
        with self._lock:
            return self._latest.get(name)

    # call this to get a snapshot of all latest samples (for gui)
    def snapshot(self):
        with self._lock:
            return dict(self._latest)


# Backward-compatible alias (older code used StoreState)
StoreState = StateStore