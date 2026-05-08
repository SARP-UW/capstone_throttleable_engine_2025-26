#!/usr/bin/env python3
"""ADS124S08 smoke test with extra diagnostics."""

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
        max_speed_hz=10_000,
        spi_mode=0b01,
    )

    return adc


def _print_register_dump(adc, label: str) -> None:
    print(f"\n{label}")

    try:
        regs = adc.rreg(0x00, 8)
        print(f"Register dump: {[f'0x{x:02X}' for x in regs]}")

        if all(x == 0x00 for x in regs):
            print("Interpretation: all 0x00; likely MISO stuck low, reset issue, or SPI not communicating.")

        elif all(x == 0xFF for x in regs):
            print("Interpretation: all 0xFF; likely MISO floating/high, wrong CS, or SPI not communicating.")

        else:
            print("Interpretation: non-uniform register values; SPI is probably communicating.")

    except Exception as e:
        print(f"Register dump FAILED: {e}")


def _spi_write_read_tests(adc) -> None:
    print("\n--- SPI WRITE/READBACK TESTS ---")

    tests = [
        ("PGA", adc.REG_PGA, 0x00),
        ("PGA", adc.REG_PGA, 0x05),
        ("PGA", adc.REG_PGA, 0x00),
        ("REF", adc.REG_REF, 0x00),
    ]

    for name, addr, value in tests:
        try:
            print(f"\nWriting {name} register 0x{addr:02X} = 0x{value:02X}")
            adc.wreg(addr, [value])
            time.sleep(0.01)

            readback = adc.rreg(addr, 1)[0]
            print(f"Readback {name}: 0x{readback:02X}")

            if readback == value:
                print("Result: write/readback matched.")
            else:
                print("Result: write/readback did NOT match.")

        except Exception as e:
            print(f"{name} write/read test FAILED: {e}")

    print("--- END SPI WRITE/READBACK TESTS ---")


def _check_drdy_pin(adc_id: str, adc) -> None:
    print(f"\n[{adc_id}] Checking DRDY state manually...")

    level = adc.get_drdy_level()

    if level is None:
        print("No DRDY pin configured.")
        return

    print(f"Initial DRDY level: {level}")

    if level == "HIGH":
        print("Interpretation: DRDY is not ready right now.")
    else:
        print("Interpretation: DRDY is LOW, meaning data-ready or line is held low.")


def _check_one(adc_id: str, cfg: dict, ain: int) -> int:
    adc = _build_adc(adc_id, cfg)

    try:
        # print(f"\n[{adc_id}] Performing reset...")
        # adc.hardware_reset()
        adc.stop()
        adc._send_cmd(adc.CMD_SDATAC)
        time.sleep(0.01)

        print(adc.rreg(0x00, 8))

        time.sleep(0.05)

        _print_register_dump(adc, "--- REGISTER DUMP AFTER RESET ---")

        _spi_write_read_tests(adc)

        _print_register_dump(adc, "--- REGISTER DUMP AFTER WRITE/READBACK TESTS ---")

        print(f"\n[{adc_id}] Configuring ADC...")
        adc.configure_basic(use_internal_ref=False, gain=1)

        print(f"\n[{adc_id}] Sending START command...")
        adc.start()

        time.sleep(0.01)

        _check_drdy_pin(adc_id, adc)

        print(f"\n[{adc_id}] Waiting for DRDY...")
        ok = adc.wait_drdy(0.5)

        print(f"[{adc_id}] DRDY result: {ok}")

        if not ok:
            print(f"\n[{adc_id}] DRDY TIMEOUT")
            print("Most likely causes now:")
            print("  - SPI data path issue: MOSI/MISO/SCLK")
            print("  - Wrong SPI mode")
            print("  - DOUT/DRDY confusion")
            print("  - ADC DOUT not connected to Pi MISO")
            print("  - ADC not actually receiving START command")
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

    ap.add_argument("--adc", default=None, help="ADC id, e.g. ADC1/ADC2/ADC3")
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
            if not isinstance(adc_id, str):
                continue

            if not isinstance(cfg, dict):
                continue

            rc |= _check_one(adc_id, cfg, args.ain)

        return rc

    if not args.adc:
        print("Provide --adc ADC1, or use --all")
        return 2

    cfg = adcs.get(args.adc)

    if not isinstance(cfg, dict):
        print(f"Unknown ADC id: {args.adc}")
        return 2

    return _check_one(args.adc, cfg, args.ain)


if __name__ == "__main__":
    raise SystemExit(main())