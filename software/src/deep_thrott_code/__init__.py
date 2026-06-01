from __future__ import annotations


def create_app(state_store, command_queue):
    from flask import Flask

    from .gui.extensions import socketio
    from .gui.routes import main_bp
    from .gui.sockets import register_socket_handlers

    app = Flask(
        __name__,
        template_folder="gui/template",
        static_folder="gui/static",
        static_url_path="/static",
    )

    app.config["SECRET_KEY"] = "dev"

    app.state_store = state_store
    app.command_queue = command_queue

    app.register_blueprint(main_bp)

    socketio.init_app(app)
    register_socket_handlers(socketio, app)

    return app