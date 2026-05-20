#!/usr/bin/env python3
"""Plot a DAQ CSV log (grouped by sensor_name).

Reads a CSV produced by deep_thrott_code's CsvLogger and plots the `value`
column over time for each sensor.

Examples:
  python software/scripts/plot_daq_csv.py daq_backend_log.csv
  python software/scripts/plot_daq_csv.py daq_backend_log.csv --sensors CC-PT FI-PT
  python software/scripts/plot_daq_csv.py daq_backend_log.csv --out plot.png

Notes:
- Required columns: sensor_name, value
- Optional time column: t_wall (preferred) or t_monotonic
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def _to_float(x: object) -> float | None:
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "none" or s.lower() == "nan":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _read_series(
    path: Path,
    *,
    sensor_allowlist: set[str] | None = None,
) -> tuple[dict[str, list[tuple[float, float]]], str]:
    """Return {sensor_name: [(t, value), ...]}, and the time field used."""

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit("CSV appears to have no header")

        fields = {name.strip() for name in reader.fieldnames if isinstance(name, str)}
        if "sensor_name" not in fields or "value" not in fields:
            raise SystemExit(
                f"CSV missing required columns. Found: {sorted(fields)}; need: sensor_name,value"
            )

        if "t_wall" in fields:
            t_field = "t_wall"
        elif "t_monotonic" in fields:
            t_field = "t_monotonic"
        else:
            t_field = ""  # fallback to index

        series: dict[str, list[tuple[float, float]]] = defaultdict(list)
        idx = 0.0

        for row in reader:
            name = (row.get("sensor_name") or "").strip()
            if not name:
                continue
            if sensor_allowlist is not None and name not in sensor_allowlist:
                continue

            v = _to_float(row.get("value"))
            if v is None:
                continue

            if t_field:
                t = _to_float(row.get(t_field))
                if t is None:
                    continue
            else:
                t = idx

            series[name].append((t, v))
            idx += 1.0

    # Ensure each series is time-sorted.
    for name in list(series.keys()):
        series[name].sort(key=lambda tv: tv[0])

    return dict(series), (t_field or "index")


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot DAQ CSV grouped by sensor_name")
    ap.add_argument(
        "csv",
        nargs="?",
        default="daq_backend_log.csv",
        help="Path to CSV log (default: daq_backend_log.csv)",
    )
    ap.add_argument(
        "--sensors",
        nargs="*",
        default=None,
        help="Optional list of sensor_name values to plot (exact match)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="If set, save plot to this path instead of showing interactively",
    )

    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    allow = set(args.sensors) if args.sensors else None

    series, t_field = _read_series(path, sensor_allowlist=allow)
    if not series:
        raise SystemExit("No plottable data found (check sensor filter / value column)")

    # Lazy import so the script can still print errors without matplotlib installed.
    import matplotlib.pyplot as plt

    # Normalize time: start at 0 for readability.
    t0 = min(tv[0] for points in series.values() for tv in points)

    plt.figure(figsize=(12, 6))
    for name, points in sorted(series.items(), key=lambda kv: kv[0]):
        xs = [t - t0 for (t, _v) in points]
        ys = [v for (_t, v) in points]
        plt.plot(xs, ys, label=name, linewidth=1.2)

    plt.xlabel(f"{t_field} (relative)")
    plt.ylabel("value")
    plt.title(path.name)
    plt.grid(True, alpha=0.25)
    plt.legend(loc="best", fontsize=8, ncols=2)
    plt.tight_layout()

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out, dpi=160)
        print(f"Saved: {out}")
    else:
        plt.show()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
