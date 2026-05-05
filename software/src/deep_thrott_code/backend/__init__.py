"""Backend package.

This package provides clearer module names for backend responsibilities:
- app creation / CLI parsing
- DAQ runtime lifecycle (threads, logging)
- GUI control-command handling

These modules are the canonical home for backend responsibilities.
"""

from .app_factory import BackendConfig, create_backend_app, parse_args
from .daq_runtime import DaqRuntime, drain_queue, emit_system
from .gui_command_handler import GuiCommandHandler

__all__ = [
    "BackendConfig",
    "create_backend_app",
    "parse_args",
    "DaqRuntime",
    "drain_queue",
    "emit_system",
    "GuiCommandHandler",
]
