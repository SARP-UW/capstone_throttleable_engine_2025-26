
from __future__ import annotations

import warnings
from typing import Any, Callable, Optional


class _DummySocketIO:
	"""Minimal stand-in for Flask-SocketIO.

	Keeps the GUI runnable even if `flask_socketio` isn't installed yet.
	"""

	is_dummy = True

	def init_app(self, app: Any, **_: Any) -> None:  # noqa: ANN401
		self._app = app

	def run(
		self,
		app: Any,  # noqa: ANN401
		host: str = "127.0.0.1",
		port: int = 5000,
		debug: bool = False,
		**kwargs: Any,  # noqa: ANN401
	) -> None:
		app.run(host=host, port=port, debug=debug, **kwargs)

	def on(self, *_: Any, **__: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:  # noqa: ANN401
		def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
			return func

		return decorator

	def emit(self, *_: Any, **__: Any) -> None:  # noqa: ANN401
		return None

try:
	from flask_socketio import SocketIO  # type: ignore
	socketio: Any = SocketIO(
		async_mode="threading",
		cors_allowed_origins="*",
		logger=True,
		engineio_logger=True,
	)
	socketio.is_dummy = False

except ImportError:
	warnings.warn(
		"flask_socketio is not installed; falling back to dummy SocketIO (no realtime updates).",
		RuntimeWarning,
	)
	socketio = _DummySocketIO()

