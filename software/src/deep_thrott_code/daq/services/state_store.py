import threading
from .sample import Sample

class StateStore:
    def __init__(self):
        self._latest = {}
        self._lock = threading.Lock()

    # Consumer calls this to update the latest sample for a sensor
    def update_sample(self, sample: Sample):
        with self._lock:
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