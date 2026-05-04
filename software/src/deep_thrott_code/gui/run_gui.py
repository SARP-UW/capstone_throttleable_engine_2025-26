from __future__ import annotations

import argparse
import sys
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

    from deep_thrott_code.gui import create_gui_app  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Deep Thrott Code GUI (frontend-only)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for serving the GUI")
    parser.add_argument("--port", type=int, default=5000, help="Bind port for serving the GUI")
    parser.add_argument(
        "--backend",
        default="",
        help="Backend Socket.IO base URL (e.g. http://pi-host:6001). If empty, frontend derives http(s)://<gui-host>:6001.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug")
    args = parser.parse_args()

    # Frontend-only: do not init Socket.IO server, do not start DAQ loops.
    app = create_gui_app(
        gui_queue=None,
        command_queue=None,
        control_queue=None,
        backend_socket_url=str(args.backend),
        enable_socketio=False,
    )

    app.run(host=str(args.host), port=int(args.port), debug=bool(args.debug), use_reloader=False)


if __name__ == "__main__":
    main()
