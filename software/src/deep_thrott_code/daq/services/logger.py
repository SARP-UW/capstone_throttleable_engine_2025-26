import csv
import os
from pathlib import Path

# change logger to argument
class CsvLogger:
    def __init__(self, filepath: str, header, flush_every: int = 25, fsync_every_flush: bool = True):
        self.filepath = Path(filepath)
        self.flush_every = flush_every
        self.fsync_every_flush = fsync_every_flush

        self.file = self.filepath.open("w", newline="")
        self.writer = csv.writer(self.file)

        self.header = header
        self.writer.writerow(self.header)
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
            sample.V_diff_1,
            sample.V_diff_2,
            sample.value,
            sample.units,
            sample.filtered_value,
            sample.source,
        ]

    # writing daq samples
    def write(self, sample) -> None:
        self._buffer.append(self._sample_to_row(sample))

        if len(self._buffer) >= self.flush_every:
            self.flush()

    # writing valve actions
    def write_valve_action(self, valve_action) -> None:
        self._buffer.append(valve_action)

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