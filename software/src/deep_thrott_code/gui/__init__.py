
from __future__ import annotations

import queue
from flask import Flask

from .extensions import socketio
from .routes import main_bp
from .sockets import register_socket_handlers


def create_gui_app(*, gui_queue: queue.Queue | None = None, command_queue: queue.Queue | None = None) -> Flask:
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

	app.register_blueprint(main_bp)

	socketio.init_app(app)
	register_socket_handlers(socketio, app, gui_queue=gui_queue, command_queue=command_queue)

	return app

