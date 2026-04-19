from __future__ import annotations

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
    from deep_thrott_code.gui.extensions import socketio  # noqa: PLC0415

    app = create_gui_app()
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":
    main()
