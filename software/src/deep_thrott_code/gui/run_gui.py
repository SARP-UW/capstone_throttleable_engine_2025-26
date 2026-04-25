from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path


class _DaqController:
    def __init__(
        self,
        *,
        gui_queue: queue.Queue,
        command_queue: queue.Queue,
        socketio,
        app,
    ) -> None:
        self._gui_queue = gui_queue
        self._command_queue = command_queue
        self._socketio = socketio
        self._app = app

        self._lock = threading.Lock()
        self._simulation_enabled = True
        self._running = False

        self._sample_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._stop_event: threading.Event | None = None
        self._producer_thread: threading.Thread | None = None
        self._consumer_thread: threading.Thread | None = None
        self._logger = None
        self._state_store = None

    def _emit(self, text: str) -> None:
        try:
            self._socketio.emit("system_message", {"text": text})
        except Exception:
            pass

    def _clear_gui_states(self) -> None:
        latest_states = self._app.config.get("LATEST_STATES")
        latest_lock = self._app.config.get("LATEST_LOCK")

        if isinstance(latest_states, dict) and isinstance(latest_lock, type(threading.Lock())):
            with latest_lock:
                latest_states.clear()

    @staticmethod
    def _drain_queue(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except Exception:
                break
            else:
                try:
                    q.task_done()
                except Exception:
                    pass

    def set_simulation_enabled(self, enabled: bool) -> None:
        enabled_bool = bool(enabled)
        with self._lock:
            self._simulation_enabled = enabled_bool
            running = self._running

        if running:
            self._emit("Simulation Mode updated; takes effect next Start Test.")
        else:

            self._emit(f"Simulation Mode set to {'ON' if enabled_bool else 'OFF'}.")

    def start(self) -> None:
        from deep_thrott_code.daq.services.loop import consumer_loop, producer_loop  # noqa: PLC0415
        from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
        from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
        from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415

        with self._lock:
            if self._running:
                self._emit("Test already running.")
                return
            simulation = self._simulation_enabled

        try:
            sensors = build_sensors(simulation=simulation)
        except Exception as e:
            self._emit(str(e))
            return

        sensor_map = build_sensor_map(sensors)
        stop_event = threading.Event()
        state_store = StateStore()
        logger = CsvLogger("daq_gui_log.csv", flush_every=25, fsync_every_flush=False)

        self._drain_queue(self._sample_queue)
        self._drain_queue(self._gui_queue)

        producer_thread = threading.Thread(
            target=producer_loop,
            args=(sensors, self._sample_queue, stop_event, 50.0),
            daemon=True,
            name="producer",
        )

        consumer_thread = threading.Thread(
            target=consumer_loop,
            args=(self._sample_queue, self._gui_queue, state_store, logger, stop_event, sensor_map),
            daemon=True,
            name="consumer",
        )

        producer_thread.start()
        consumer_thread.start()

        with self._lock:
            self._stop_event = stop_event
            self._producer_thread = producer_thread
            self._consumer_thread = consumer_thread
            self._logger = logger
            self._state_store = state_store
            self._running = True

        self._emit(f"Test started ({'SIM' if simulation else 'ADC'} mode).")

    def stop(self) -> None:
        stop_event = None
        producer_thread = None
        consumer_thread = None
        logger = None

        with self._lock:
            if not self._running:
                self._emit("No test running.")
                return
            stop_event = self._stop_event
            producer_thread = self._producer_thread
            consumer_thread = self._consumer_thread
            logger = self._logger
            self._running = False
            self._stop_event = None
            self._producer_thread = None
            self._consumer_thread = None
            self._logger = None
            self._state_store = None

        if stop_event is not None:
            stop_event.set()

        if producer_thread is not None:
            producer_thread.join(timeout=1.0)
        if consumer_thread is not None:
            consumer_thread.join(timeout=1.0)

        try:
            if logger is not None:
                logger.close()
        except Exception:
            pass

        self._drain_queue(self._sample_queue)
        self._drain_queue(self._gui_queue)
        self._emit("Test stopped.")


def _ensure_src_on_path() -> None:
    # This file lives at: software/src/deep_thrott_code/gui/run_gui.py
    # We want: software/src on sys.path so `import deep_thrott_code` works
    src_dir = Path(__file__).resolve().parents[2]
    src_dir_str = str(src_dir)
    if src_dir_str not in sys.path:
        sys.path.insert(0, src_dir_str)


def main() -> None:
    _ensure_src_on_path()

    from deep_thrott_code.gui import create_gui_app  # noqa: PLC0415
    from deep_thrott_code.gui.extensions import socketio  # noqa: PLC0415

    gui_queue: queue.Queue = queue.Queue(maxsize=1000)
    command_queue: queue.Queue = queue.Queue(maxsize=100)
    app = create_gui_app(gui_queue=gui_queue, command_queue=command_queue)

    controller = _DaqController(gui_queue=gui_queue, command_queue=command_queue, socketio=socketio, app=app)

    def command_loop() -> None:
        while True:
            payload = command_queue.get()
            try:
                if not isinstance(payload, dict):
                    controller._emit("Ignored non-object command payload.")
                    continue

                name = payload.get("name")
                if name == "set_simulation":
                    controller.set_simulation_enabled(bool(payload.get("enabled")))
                elif name == "start_test":
                    controller.start()
                elif name == "stop_test":
                    controller.stop()
                else:
                    controller._emit(f"Unknown command: {name}")
            finally:
                try:
                    command_queue.task_done()
                except Exception:
                    pass

    threading.Thread(target=command_loop, daemon=True, name="command_loop").start()
    socketio.run(app, host="127.0.0.1", port=5000, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
