from __future__ import annotations

import argparse
import queue
import threading
from dataclasses import dataclass

from flask import Flask

from deep_thrott_code.gui.extensions import socketio
from deep_thrott_code.gui.sockets import register_socket_handlers


@dataclass(frozen=True)
class BackendConfig:
    host: str
    port: int
    debug: bool
    autostart: bool
    simulation: bool


class BackendController:
    def __init__(
        self,
        *,
        gui_queue: queue.Queue,
        control_queue: queue.Queue,
        socketio_obj,
    ) -> None:
        self._gui_queue = gui_queue
        self._control_queue = control_queue
        self._socketio = socketio_obj

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
            self._emit("Simulation Mode updated; takes effect next Start Log.")
        else:
            self._emit(f"Simulation Mode set to {'ON' if enabled_bool else 'OFF'}.")

    def start(self) -> None:
        from deep_thrott_code.daq.services.loop import consumer_loop, producer_loop  # noqa: PLC0415
        from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
        from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
        from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415

        with self._lock:
            if self._running:
                self._emit("Log already running.")
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
        logger = CsvLogger("daq_backend_log.csv", flush_every=25, fsync_every_flush=False)

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

        self._emit(f"Backend log started ({'SIM' if simulation else 'ADC'} mode).")

    def stop(self) -> None:
        stop_event = None
        producer_thread = None
        consumer_thread = None
        logger = None

        with self._lock:
            if not self._running:
                self._emit("No log running.")
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
        self._emit("Backend log stopped.")

    def command_loop_forever(self) -> None:
        while True:
            payload = self._control_queue.get()
            try:
                if not isinstance(payload, dict):
                    self._emit("Ignored non-object command payload.")
                    continue

                name = payload.get("name")
                if name == "set_simulation":
                    self.set_simulation_enabled(bool(payload.get("enabled")))
                elif name == "start_log":
                    self.start()
                elif name == "stop_log":
                    self.stop()
                else:
                    self._emit(f"Unknown command: {name}")
            finally:
                try:
                    self._control_queue.task_done()
                except Exception:
                    pass


def parse_args() -> BackendConfig:
    parser = argparse.ArgumentParser(description="Deep Thrott Code backend (DAQ + Socket.IO)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (0.0.0.0 to listen on LAN)")
    parser.add_argument("--port", type=int, default=6000, help="Bind port for backend Socket.IO")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug")
    parser.add_argument("--autostart", action="store_true", help="Start logging immediately")
    parser.add_argument(
        "--simulation",
        action="store_true",
        help="Default to Simulation Mode ON at startup (still changeable via GUI)",
    )
    args = parser.parse_args()
    return BackendConfig(
        host=str(args.host),
        port=int(args.port),
        debug=bool(args.debug),
        autostart=bool(args.autostart),
        simulation=bool(args.simulation),
    )


def create_backend_app(
    *,
    gui_queue: queue.Queue,
    command_queue: queue.Queue,
    control_queue: queue.Queue,
) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev"

    socketio.init_app(app)
    register_socket_handlers(
        socketio,
        app,
        gui_queue=gui_queue,
        command_queue=command_queue,
        control_queue=control_queue,
    )
    return app


def main() -> None:
    cfg = parse_args()

    if getattr(socketio, "is_dummy", False):
        raise RuntimeError(
            "flask_socketio is required for the backend service. "
            "Install `flask-socketio` (and deps) in this environment."
        )

    gui_queue: queue.Queue = queue.Queue(maxsize=1000)
    # command_queue: raw string commands intended for an eventual F3 loop (e.g., "fill", "fire").
    command_queue: queue.Queue = queue.Queue(maxsize=100)
    # control_queue: structured GUI control commands for backend controller.
    control_queue: queue.Queue = queue.Queue(maxsize=100)

    app = create_backend_app(gui_queue=gui_queue, command_queue=command_queue, control_queue=control_queue)
    controller = BackendController(gui_queue=gui_queue, control_queue=control_queue, socketio_obj=socketio)

    controller.set_simulation_enabled(cfg.simulation)
    threading.Thread(target=controller.command_loop_forever, daemon=True, name="backend_command_loop").start()

    if cfg.autostart:
        controller.start()

    # NOTE: `host=0.0.0.0` makes the backend reachable from other machines.
    socketio.run(app, host=cfg.host, port=cfg.port, debug=cfg.debug, use_reloader=False)


if __name__ == "__main__":
    main()