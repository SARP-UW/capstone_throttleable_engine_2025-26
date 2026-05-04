from flask import Blueprint, current_app, render_template

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    backend_socket_url = current_app.config.get("BACKEND_SOCKET_URL", "")
    return render_template("index.html", backend_socket_url=backend_socket_url)