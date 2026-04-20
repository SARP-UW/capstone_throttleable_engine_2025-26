import csv
import os
from pathlib import Path

# change logger to argument
class CsvLogger:
    HEADER = [
        "sensor_name",
        "sensor_kind",
        "t_monotonic",
        "t_wall",
        "raw_value",
        "value",
        "units",
        "status",
        "message",
        "filtered_value",
        "sequence",
        "source",
    ]

    def __init__(self, filepath: str, flush_every: int = 25, fsync_every_flush: bool = True):
        self.filepath = Path(filepath)
        self.flush_every = flush_every
        self.fsync_every_flush = fsync_every_flush

        self.file = self.filepath.open("w", newline="")
        self.writer = csv.writer(self.file)

        self.writer.writerow(self.HEADER)
        self.file.flush()
        if self.fsync_every_flush:
            os.fsync(self.file.fileno())

        self._buffer: list[list] = []

    def _sample_to_row(self, sample) -> list:
        return [
            sample.sensor_name,
            sample.sensor_kind,
            sample.t_monotonic,
            sample.t_wall,
            sample.raw_value,
            sample.value,
            sample.units,
            sample.status,
            sample.message,
            sample.filtered_value,
            sample.sequence,
            sample.source,
        ]
    
    # make f3 + throttle loop write to row method

    def write(self, sample) -> None:
        self._buffer.append(self._sample_to_row(sample))

        if len(self._buffer) >= self.flush_every:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return

        self.writer.writerows(self._buffer)
        self._buffer.clear()

        self.file.flush()
        if self.fsync_every_flush:
            os.fsync(self.file.fileno())

    def close(self) -> None:
        if not self.file.closed:
            self.flush()
            self.file.close()