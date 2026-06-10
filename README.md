# capstone_throttleable_engine_2025-26

2025-2026 SARP Capstone Project — a throttleable Eth/N2O rocket engine.

This repository includes:
- **software** (`software/`) — Python DAQ, valve actuation, throttle control, and web GUI
- **hardware** (`hardware/`) — KiCAD PCB design for DAQ, valve actuation, and throttle control
- **analysis** (`analysis/`) — Thermal, structural, and control system analysis (MATLAB/Python)

---

## Software

**Package:** `deep-thrott-code` v0.1.0  
**Requires:** Python ≥ 3.10

### Installation

```bash
pip install -e .
```

### Running the GUI

The system is split into two servers:

| Server | Default address | Role |
|--------|----------------|------|
| **Backend** (`main.py`) | `http://0.0.0.0:6001` | DAQ, valve control, F3C sequencer, Socket.IO |
| **GUI** (`gui/`) | `http://127.0.0.1:5000` | Serves the web frontend only |

When you open the GUI in a browser, the frontend JS automatically connects to the backend via Socket.IO on port 6001 (same host, different port). The backend streams live sensor data at ~10 Hz and receives commands (valve actuation, sequence control, start/stop logging) from the GUI.

**Running both on the same machine:**

```bash
# Terminal 1 — start the backend
python -m deep_thrott_code.main --host 0.0.0.0 --port 6001

# Terminal 2 — start the GUI server
python -m deep_thrott_code.gui --host 0.0.0.0 --port 5000
```

Once the server is running, open any browser on the same network and navigate to:

```
http://<host-ip>:5000
```

If running locally, just go to `http://localhost:5000` or `http://127.0.0.1:5000`.  
If running on a Raspberry Pi, use the Pi's IP address: `http://192.168.x.x:5000`.

**Running backend on a Pi, GUI on your laptop:**

```bash
# On the Pi
python -m deep_thrott_code.main --host 0.0.0.0 --port 6001

# On your laptop (point GUI at the Pi's IP)
python -m deep_thrott_code.gui --backend http://192.168.x.x:6001 --host 127.0.0.1 --port 5000
```

Then open `http://localhost:5000` on your laptop.

**What you see in the browser:**

The GUI is a single-page app with:
- **Line control tabs** — PID diagrams with live valve state and pressure readouts for ethanol and nitrous lines
- **DAQ tabs** — 18 real-time sensor plots (auto-scaled, 300-point history)
- **Sequence panel** — step-by-step fire sequence tracking with manual step execution
- **Settings** — simulation toggle, test selection (hotfire / cold flow), sensor selection, theme

**CLI flags (main backend):**

| Flag | Description |
|------|-------------|
| `--host` | Bind host (default `0.0.0.0`) |
| `--port` | Bind port (default `6001`) |
| `--simulation` | Run without hardware (sensor simulation) |
| `--no-gui-server` | Start backend only, no Flask server |
| `--autostart` | Automatically start DAQ on launch |
| `--no-sequencer` | Disable the F3C fire sequencer |
| `--debug` | Enable Flask debug mode |

### Structure

```
software/src/deep_thrott_code/
├── main.py               # Entry point
├── backend/              # App factory, GUI command handlers, DAQ runtime
├── gui/                  # Flask + Socket.IO web interface (routes, sockets)
├── daq/                  # Data acquisition — ADC drivers and sensor interfaces
├── f3c/                  # Flight control sequencer and valve control
├── control/              # PID throttle controller and servo characterization
└── config/               # Default configuration files
```

**Utility scripts** (`software/scripts/`):
- `hotfire.py` — Hotfire sequence runner
- `calibrate_sensors.py` — Sensor calibration
- `plot_daq_csv.py` — Plot data from DAQ CSV logs
- `adc_smoke_test.py` — ADC hardware smoke test

### Dependencies

| Package | Purpose |
|---------|---------|
| Flask, Flask-SocketIO | Web GUI server |
| NumPy, SciPy | Numerical computation |
| PyYAML | Configuration parsing |
| PySerial | Serial communication |
| Matplotlib | Data visualization |
| RPi.GPIO, pigpio, spidev | GPIO and SPI (Linux/RPi only) |
| eventlet *(optional)* | Async server mode |

---

## Hardware

KiCAD project located in `hardware/cda-pcb/`. Includes schematic, PCB layout, Gerber files, and custom symbols/footprints.

---

## Analysis

- `analysis/control_dev/` — Control system models (MATLAB and Python)
- `analysis/engine_dev/` — Structural analysis (Python, based on GRACE methodology)

