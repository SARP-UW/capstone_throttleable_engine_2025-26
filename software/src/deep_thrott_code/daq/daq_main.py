"""DAQ entrypoints.

Default behavior (no special flags): run the full backend GUI service.

For Raspberry Pi bring-up / hardware testing, you can run a lightweight,
headless DAQ loop (no Flask/Socket.IO) using either:

- `python -m deep_thrott_code.daq.daq_main --headless`
- `python -m deep_thrott_code.daq.daq_main headless`
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from pathlib import Path


# Allow running this file directly (e.g., on the Pi) without installing the package.
# When invoked as a script, Python adds the *file's directory* to sys.path, which
# is deep_thrott_code/daq; we need software/src on sys.path for absolute imports.
if __package__ in (None, ""):
    pkg_root = Path(__file__).resolve().parents[2]
    if str(pkg_root) not in sys.path:
        sys.path.insert(0, str(pkg_root))


def _build_headless_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Headless DAQ runner (Pi test harness)")
    p.add_argument(
        "--simulation",
        action="store_true",
        help="Use simulated sensors instead of ADC hardware (default: ADC/hardware)",
    )
    p.add_argument("--loop-hz", type=float, default=50.0, help="Producer loop rate")
    p.add_argument("--log-path", default="daq_pi_log.csv", help="CSV output path")
    p.add_argument("--print-every-s", type=float, default=1.0, help="Console print period")
    p.add_argument(
        "--duration-s",
        type=float,
        default=0.0,
        help="Stop after N seconds (0 = run until Ctrl+C)",
    )
    return p


def _run_headless(argv: list[str]) -> int:
    from deep_thrott_code.daq.services.loop import consumer_loop, producer_loop  # noqa: PLC0415
    from deep_thrott_code.daq.services.logger import CsvLogger  # noqa: PLC0415
    from deep_thrott_code.daq.services.state_store import StateStore  # noqa: PLC0415
    from deep_thrott_code.daq.sensors.sensors import build_sensor_map, build_sensors  # noqa: PLC0415

    args = _build_headless_parser().parse_args(argv)

    gui_queue: queue.Queue = queue.Queue(maxsize=1000)
    sample_queue: queue.Queue = queue.Queue(maxsize=1000)
    stop_event = threading.Event()
    state_store = StateStore()
    logger = CsvLogger(str(args.log_path), flush_every=25, fsync_every_flush=True)

    sensors = build_sensors(simulation=bool(args.simulation))
    sensor_map = build_sensor_map(sensors)
    expected_names = [s.name for s in sensors]

    producer_thread = threading.Thread(
        target=producer_loop,
        args=(sensors, sample_queue, stop_event, float(args.loop_hz)),
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

    mode = "SIM" if args.simulation else "ADC"
    print(f"Headless DAQ started ({mode}) -> {args.log_path}")
    print("Press Ctrl+C to stop.")

    t0 = time.perf_counter()
    next_print = t0
    try:
        while True:
            now = time.perf_counter()
            if args.duration_s and (now - t0) >= float(args.duration_s):
                break

            if now >= next_print:
                snap = state_store.snapshot()
                missing = [n for n in expected_names if n not in snap]
                if missing:
                    print(f"waiting for samples... missing={missing} qsize={sample_queue.qsize()}")
                else:
                    parts = []
                    for name in expected_names:
                        s = snap[name]
                        v = "--" if s.value is None else f"{s.value:.3f}"
                        parts.append(f"{name}={v} {s.units} [{s.status}]")
                    print(" | ".join(parts))
                next_print = now + float(args.print_every_s)

            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        producer_thread.join(timeout=2.0)
        consumer_thread.join(timeout=2.0)
        try:
            logger.close()
        except Exception:
            pass

        # Best-effort: close any shared ADC instances.
        seen = set()
        for sensor in sensors:
            adc = getattr(sensor, "adc", None)
            if adc is None:
                continue
            adc_id = id(adc)
            if adc_id in seen:
                continue
            seen.add(adc_id)
            close = getattr(adc, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    print("Headless DAQ stopped.")
    return 0


def main() -> None:
    argv = list(sys.argv)

    # Opt-in headless mode for Pi bring-up.
    if len(argv) > 1 and argv[1] == "headless":
        raise SystemExit(_run_headless(argv[2:]))
    if "--headless" in argv:
        filtered = [a for a in argv[1:] if a != "--headless"]
        raise SystemExit(_run_headless(filtered))

    # Default: run the full backend (GUI server + DAQ runtime).
    from deep_thrott_code.main import main as backend_main  # noqa: PLC0415

    backend_main()


if __name__ == "__main__":
    main()