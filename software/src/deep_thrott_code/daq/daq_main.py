"""Compatibility wrapper.

The backend implementation lives in `deep_thrott_code.main`.
Keeping this module allows existing commands like:

`python -m deep_thrott_code.daq.daq_main`

to continue working.
"""

from __future__ import annotations

from deep_thrott_code.main import main


if __name__ == "__main__":
    main()