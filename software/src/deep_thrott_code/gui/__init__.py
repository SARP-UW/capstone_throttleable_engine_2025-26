
from __future__ import annotations

import queue
from flask import Flask

from .extensions import socketio
from .routes import main_bp
from .sockets import register_socket_handlers


def create_gui_app(
    *,
    gui_queue: queue.Queue | None = None,
    command_queue: queue.Queue | None = None,
    control_queue: queue.Queue | None = None,
    backend_socket_url: str | None = None,
    enable_socketio: bool = True,
) -> Flask:
    """Create the standalone GUI web server.

    This is intentionally minimal: it serves the mockup frontend and exposes
    placeholders for later Socket.IO wiring.
    """

    app = Flask(
        __name__,
        template_folder="template",
        static_folder="static",
        static_url_path="/static",
    )
    app.config["SECRET_KEY"] = "dev"
    if backend_socket_url is not None:
        app.config["BACKEND_SOCKET_URL"] = str(backend_socket_url)

    app.register_blueprint(main_bp)

    if enable_socketio:
        socketio.init_app(app)
        register_socket_handlers(
            socketio,
            app,
            gui_queue=gui_queue,
            command_queue=command_queue,
            control_queue=control_queue,
        )

    return app

