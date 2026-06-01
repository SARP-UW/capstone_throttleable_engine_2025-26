
from __future__ import annotations

import os
import warnings
from typing import Any, Callable, Optional

try:
	configured_async_mode = os.environ.get("DEEP_THROTT_SOCKETIO_ASYNC_MODE", "threading").strip().lower()
	async_mode = configured_async_mode or "threading"
	if async_mode == "eventlet":
		import eventlet  # type: ignore
		eventlet.monkey_patch()  # type: ignore

	from flask_socketio import SocketIO  # type: ignore
	socketio: Any = SocketIO(
		async_mode=async_mode,
		cors_allowed_origins="*",
		serve_client=True,
		# Keep terminal output readable; enable these only when debugging Socket.IO internals.
		logger=False,
		engineio_logger=False,
	)
	socketio.is_dummy = False

except ImportError:
	warnings.warn(
		"flask_socketio is not installed",
		RuntimeWarning,
	)
