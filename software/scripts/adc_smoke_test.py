#!/usr/bin/env python3
"""ADS124S08 smoke test (Pi only).

Runs a minimal bring-up against the configured ADCs in config/hardware.yml:
- Open SPI device
- Optionally assert START/SYNC GPIO
- Poll DRDY
- Read a couple raw samples

This bypasses the backend/GUI so you can debug SPI/CS/DRDY wiring.

Usage (from repo root on Pi):
  python3 software/scripts/adc_smoke_test.py --adc ADC3 --ain 9
  python3 software/scripts/adc_smoke_test.py --all

Notes:
- Requires Linux + spidev + gpiod installed.
- GPIO numbers are assumed to be gpiochip line offsets (on Pi gpiochip0 these
  usually match BCM GPIO numbers; verify with `gpioinfo` if unsure).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _repo_src_on_path() -> None:
    # Make `deep_thrott_code` importable without needing an editable install.
    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "software" / "src"
    sys.path.insert(0, str(src))


def _load_hardware_cfg() -> dict:
    import yaml  # type: ignore

    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "software" / "src" / "deep_thrott_code" / "config" / "hardware.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _build_adc(adc_id: str, cfg: dict):
    from deep_thrott_code.daq.drivers.adc import ADS124S08

    spi_bus = int(cfg["spi_bus"])
    spi_dev = int(cfg["spi_device"])
    cs_gpio = cfg.get("cs_gpio")
    drdy_gpio = cfg.get("drdy_gpio")
    start_gpio = cfg.get("start_sync_gpio")

    cs_pin = int(cs_gpio) if cs_gpio is not None else None
    drdy_pin = int(drdy_gpio) if drdy_gpio is not None else None
    start_pin = int(start_gpio) if start_gpio is not None else None

    adc = ADS124S08(
        id=adc_id,
        spi_bus=spi_bus,
        spi_dev=spi_dev,
        cs_pin=cs_pin,
        drdy_pin=drdy_pin,
        start_pin=start_pin,
        reset_pin=None,
    )
    adc.hardware_reset()
    adc.configure_basic(use_internal_ref=False, gain=1)
    adc.start()
    return adc


def _check_one(adc_id: str, cfg: dict, ain: int) -> int:
    adc = _build_adc(adc_id, cfg)
    try:
        print(f"[{adc_id}] waiting for DRDY...")
        ok = adc.wait_drdy(0.5)
        print(f"[{adc_id}] DRDY ok={ok}")

        # Try a couple reads.
        for i in range(3):
            try:
                code = adc.read_raw_single(int(ain), settle_discard=True)
                print(f"[{adc_id}] read {i}: AIN{ain} raw={code}")
            except TimeoutError as e:
                print(f"[{adc_id}] read {i}: TIMEOUT: {e}")
            time.sleep(0.1)
        return 0
    finally:
        adc.close()


def main() -> int:
    _repo_src_on_path()

    ap = argparse.ArgumentParser()
    ap.add_argument("--adc", default=None, help="ADC id (e.g. ADC1/ADC2/ADC3)")
    ap.add_argument("--ain", type=int, default=0, help="AIN index to read")
    ap.add_argument("--all", action="store_true", help="Check all configured ADCs")
    args = ap.parse_args()

    hw = _load_hardware_cfg()
    adcs = hw.get("adcs")
    if not isinstance(adcs, dict) or not adcs:
        print("No 'adcs' section found in hardware.yml")
        return 2

    if args.all:
        rc = 0
        for adc_id, cfg in adcs.items():
            if not isinstance(adc_id, str) or not isinstance(cfg, dict):
                continue
            rc |= _check_one(adc_id, cfg, args.ain)
        return rc

    if not args.adc:
        print("Provide --adc ADC1 (or use --all)")
        return 2

    cfg = adcs.get(args.adc)
    if not isinstance(cfg, dict):
        print(f"Unknown ADC id: {args.adc}")
        return 2

    return _check_one(args.adc, cfg, args.ain)


if __name__ == "__main__":
    raise SystemExit(main())
