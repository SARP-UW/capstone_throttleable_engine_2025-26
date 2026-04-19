
from __future__ import annotations

from typing import Any


def register_socket_handlers(socketio: Any, app: Any) -> None:  # noqa: ANN401
	"""Register Socket.IO event handlers.

	Intentionally empty for now — the current goal is to serve the frontend
	mockup without wiring up button actions.
	"""

	_ = socketio
	_ = app

