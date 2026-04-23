from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path


def _ensure_src_on_path() -> None:
    # This file lives at: software/src/deep_thrott_code/gui/run_gui.py
    # We want: software/src on sys.path so `import deep_thrott_code` works
    src_dir = Path(__file__).resolve().parents[2]
    src_dir_str = str(src_dir)
    if src_dir_str not in sys.path:
        sys.path.insert(0, src_dir_str)


def main() -> None:
    _ensure_src_on_path()

    from deep_thrott_code.daq.services.loop import consumer_loop, producer_loop  # noqa: PLC0415
    from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
    from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
    from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415
    from deep_thrott_code.gui import create_gui_app  # noqa: PLC0415
    from deep_thrott_code.gui.extensions import socketio  # noqa: PLC0415

    sample_queue: queue.Queue = queue.Queue(maxsize=1000)
    gui_queue: queue.Queue = queue.Queue(maxsize=1000)
    command_queue: queue.Queue = queue.Queue(maxsize=100)
    stop_event = threading.Event()
    state_store = StateStore()
    logger = CsvLogger("daq_gui_log.csv", flush_every=25, fsync_every_flush=False)

    sensors = build_sensors()
    sensor_map = build_sensor_map(sensors)

    producer_thread = threading.Thread(
        target=producer_loop,
        args=(sensors, sample_queue, stop_event, 50.0),
        daemon=True,
        name="producer",
    )

    consumer_thread = threading.Thread(
        target=consumer_loop,
        args=(sample_queue, gui_queue, state_store, logger, stop_event, sensor_map),
        daemon=True,
        name="consumer",
    )

    producer_thread.start()
    consumer_thread.start()

    app = create_gui_app(gui_queue=gui_queue, command_queue=command_queue)
    socketio.run(app, host="127.0.0.1", port=5000, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
