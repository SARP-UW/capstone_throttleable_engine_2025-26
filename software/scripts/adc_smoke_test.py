#!/usr/bin/env python3
"""ADS124S08 smoke test (Pi only).

Runs a minimal bring-up against the configured ADCs in config/hardware.yml:
- Open SPI device
- Poll DRDY
- Read/write diagnostic registers
- Read a couple raw samples

Usage:
  python3 software/scripts/adc_smoke_test.py --adc ADC3 --ain 9
  python3 software/scripts/adc_smoke_test.py --all
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _repo_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "software" / "src"
    sys.path.insert(0, str(src))


def _load_hardware_cfg() -> dict:
    import yaml

    repo_root = Path(__file__).resolve().parents[2]
    path = (
        repo_root
        / "software"
        / "src"
        / "deep_thrott_code"
        / "config"
        / "hardware.yml"
    )

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

    print(f"\n[{adc_id}] Creating ADC")
    print(f"  SPI bus/dev : {spi_bus}.{spi_dev}")
    print(f"  CS GPIO     : {cs_pin}")
    print(f"  DRDY GPIO   : {drdy_pin}")
    print(f"  START GPIO  : {start_pin} (ignored by driver)")

    adc = ADS124S08(
        id=adc_id,
        spi_bus=spi_bus,
        spi_dev=spi_dev,
        cs_pin=cs_pin,
        drdy_pin=drdy_pin,
        start_pin=start_pin,
        reset_pin=None,
    )

    return adc


def _spi_diagnostics(adc):
    print("\n--- SPI DIAGNOSTICS ---")

    try:
        print("Reading first 8 registers...")
        regs = adc.rreg(0x00, 8)
        print(f"Raw register dump: {[hex(x) for x in regs]}")
    except Exception as e:
        print(f"Register read FAILED: {e}")
        return

    try:
        print("\nTesting PGA register write/readback...")
        adc.wreg(adc.REG_PGA, [0x00])
        time.sleep(0.01)

        pga = adc.rreg(adc.REG_PGA, 1)[0]
        print(f"PGA register readback: 0x{pga:02X}")

    except Exception as e:
        print(f"PGA write/read FAILED: {e}")

    try:
        print("\nTesting REF register write/readback...")
        adc.wreg(adc.REG_REF, [0x00])
        time.sleep(0.01)

        ref = adc.rreg(adc.REG_REF, 1)[0]
        print(f"REF register readback: 0x{ref:02X}")

    except Exception as e:
        print(f"REF write/read FAILED: {e}")

    print("--- END SPI DIAGNOSTICS ---\n")


def _check_drdy_pin(adc_id: str, adc):
    print(f"\n[{adc_id}] Checking DRDY state manually...")

    if adc._req_in is None or adc.drdy_pin is None:
        print("No DRDY pin configured")
        return

    try:
        val = adc._req_in.get_value(adc.drdy_pin)
        print(f"Initial DRDY GPIO value: {val}")

        if str(val).lower().endswith("active"):
            print("DRDY currently LOW")
        else:
            print("DRDY currently HIGH")

    except Exception as e:
        print(f"Failed to read DRDY pin: {e}")


def _check_one(adc_id: str, cfg: dict, ain: int) -> int:
    adc = _build_adc(adc_id, cfg)

    try:
        print(f"\n[{adc_id}] Performing hardware reset...")
        adc.hardware_reset()

        time.sleep(0.05)

        _spi_diagnostics(adc)

        print(f"\n[{adc_id}] Configuring ADC...")
        adc.configure_basic(use_internal_ref=False, gain=1)

        print(f"\n[{adc_id}] Sending START command...")
        adc.start()

        _check_drdy_pin(adc_id, adc)

        print(f"\n[{adc_id}] Waiting for DRDY...")
        ok = adc.wait_drdy(0.5)

        print(f"[{adc_id}] DRDY result: {ok}")

        if not ok:
            print(f"\n[{adc_id}] DRDY TIMEOUT")
            print("Possible causes:")
            print("  - RESET pin held low")
            print("  - SPI not communicating")
            print("  - Wrong CS GPIO")
            print("  - Wrong DRDY GPIO")
            print("  - ADC not powered")
            print("  - No common ground")
            return 1

        print(f"\n[{adc_id}] Attempting sample reads...")

        for i in range(3):
            try:
                print(f"\n[{adc_id}] Read attempt {i}")

                code = adc.read_raw_single(
                    int(ain),
                    settle_discard=True,
                )

                print(f"[{adc_id}] AIN{ain} raw code = {code}")

            except TimeoutError as e:
                print(f"[{adc_id}] TIMEOUT: {e}")

            except Exception as e:
                print(f"[{adc_id}] READ FAILED: {e}")

            time.sleep(0.1)

        return 0

    finally:
        adc.close()


def main() -> int:
    _repo_src_on_path()

    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--adc",
        default=None,
        help="ADC id (ADC1/ADC2/ADC3)",
    )

    ap.add_argument(
        "--ain",
        type=int,
        default=0,
        help="AIN index to read",
    )

    ap.add_argument(
        "--all",
        action="store_true",
        help="Check all configured ADCs",
    )

    args = ap.parse_args()

    hw = _load_hardware_cfg()

    adcs = hw.get("adcs")

    if not isinstance(adcs, dict) or not adcs:
        print("No 'adcs' section found in hardware.yml")
        return 2

    if args.all:
        rc = 0

        for adc_id, cfg in adcs.items():
            if not isinstance(adc_id, str):
                continue

            if not isinstance(cfg, dict):
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