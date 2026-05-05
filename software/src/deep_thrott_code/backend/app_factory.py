"""Backend Flask app factory + CLI config.

This module builds the backend process that the GUI connects to.

High-level architecture:
- DAQ side produces samples and pushes them onto `gui_queue`.
- A Socket.IO loop (registered in `deep_thrott_code/gui/sockets.py`) drains
	`gui_queue` and emits `daq_packet` to the browser.
- The sequencing runtime exposes a separate snapshot function; the Socket.IO
	loop emits that as `system_packet` so DAQ telemetry never overwrites GUI state.

Queues used by the backend:
- `gui_queue`: DAQ samples destined for the GUI.
- `command_queue`: high-level GUI commands intended for the sequencing runtime
	(e.g. "fill", "fire").
- `control_queue`: GUI control commands for this backend process
	(start/stop log, toggle simulation, etc.).

Note on Controller integration:
- The F3C Controller consumes commands and manual-step acknowledgements on
	separate queues (`command_queue` and `gui_to_f3_queue`).
"""

from __future__ import annotations

import argparse
import queue
from collections.abc import Callable
from dataclasses import dataclass

from flask import Flask


@dataclass(frozen=True)
class BackendConfig:
	# CLI/config values for starting the backend process.
	# (These are read once at process startup.)
	host: str
	port: int
	debug: bool
	autostart: bool
	simulation: bool


def parse_args() -> BackendConfig:
	"""Parse CLI flags for running the backend as a standalone process."""

	# We keep argument parsing here so `deep_thrott_code.main` can use it,
	# and so this module can be run directly if desired.
	parser = argparse.ArgumentParser(description="Deep Thrott Code backend (DAQ + Socket.IO)")
	# Bind host for the web server.
	parser.add_argument("--host", default="0.0.0.0", help="Bind host (0.0.0.0 to listen on LAN)")
	parser.add_argument(
		"--port",
		type=int,
		# 6000 is blocked by some browsers as an unsafe port; use 6001.
		default=6001,
		help="Bind port for backend Socket.IO (6000 is browser-unsafe; default 6001)",
	)
	# Flask debug mode (auto-reload is disabled elsewhere).
	parser.add_argument("--debug", action="store_true", help="Enable Flask debug")
	# Convenience: start DAQ logging immediately after launching the backend.
	parser.add_argument("--autostart", action="store_true", help="Start logging immediately")
	parser.add_argument(
		"--simulation",
		action="store_true",
		# Default is False, but the GUI can still toggle simulation at runtime.
		help="Default to Simulation Mode ON at startup (still changeable via GUI)",
	)
	# Parse the args and normalize types.
	args = parser.parse_args()
	return BackendConfig(
		host=str(args.host),
		port=int(args.port),
		debug=bool(args.debug),
		autostart=bool(args.autostart),
		simulation=bool(args.simulation),
    )

__all__ = ["BackendConfig", "parse_args"]
