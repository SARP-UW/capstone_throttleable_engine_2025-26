from flask import Flask
from gui.extensions import socketio
from gui.routes import main_bp
from gui.sockets import register_socket_handlers

def create_app(state_store, command_queue):
    app = Flask(__name__)

    app.config["SECRET_KEY"] = "dev"

    app.state_store = state_store
    app.command_queue = command_queue

    app.register_blueprint(main_bp)

    socketio.init_app(app)
    register_socket_handlers(socketio, app)

    return app