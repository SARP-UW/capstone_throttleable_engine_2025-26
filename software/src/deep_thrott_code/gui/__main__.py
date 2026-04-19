from __future__ import annotations

from . import create_gui_app
from .extensions import socketio

def main() -> None:
    app = create_gui_app()
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)

if __name__ == "__main__":
    main()
