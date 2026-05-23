#!/usr/bin/env python3
"""ADS124S08 smoke test using shared SPI + manual GPIO chip-select."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import spidev  # type: ignore
import RPi.GPIO as GPIO  # type: ignore


_SHARED_SPI_BY_NODE: dict[tuple[int, int], spidev.SpiDev] = {}
_SPI_LOCK_BY_BUS: dict[int, threading.Lock] = {}
_MANUAL_CS_PINS: list[int] = []


def _adc_code_to_voltage(code: int, *, vref: float = 5.0, gain: float = 1.0) -> float:
    fs_code = (1 << 23) - 1
    full_scale = float(vref) / float(gain) if gain else float(vref)
    return (float(code) / fs_code) * full_scale


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


def _collect_manual_cs_pins(adcs: dict) -> list[int]:
    pins: list[int] = []

    for adc_id, cfg in adcs.items():
        if not isinstance(adc_id, str) or not isinstance(cfg, dict):
            continue

        if str(cfg.get("transport", "")).lower() != "spi":
            continue

        if str(cfg.get("model", "")).upper() not in {"ADS124S08IRHBT", "ADS124S08"}:
            continue

        cs_gpio = cfg.get("cs_gpio")
        if cs_gpio is None:
            raise RuntimeError(
                f"{adc_id}: cs_gpio must be set. "
                "This test uses manual GPIO chip-select for all ADCs."
            )

        pins.append(int(cs_gpio))

    return pins


def _setup_gpio(adcs: dict) -> None:
    global _MANUAL_CS_PINS

    _MANUAL_CS_PINS = _collect_manual_cs_pins(adcs)

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for cs_pin in _MANUAL_CS_PINS:
        GPIO.setup(cs_pin, GPIO.OUT, initial=GPIO.HIGH)


def _get_shared_spi(spi_bus: int, spi_dev: int, max_speed_hz: int):
    spi_node = (spi_bus, spi_dev)

    if spi_node not in _SHARED_SPI_BY_NODE:
        spi = spidev.SpiDev()
        spi.open(spi_bus, spi_dev)
        spi.mode = 0b01
        spi.max_speed_hz = int(max_speed_hz)
        spi.bits_per_word = 8
        spi.no_cs = True

        _SHARED_SPI_BY_NODE[spi_node] = spi
    else:
        spi = _SHARED_SPI_BY_NODE[spi_node]
        spi.max_speed_hz = int(max_speed_hz)
        spi.no_cs = True

    spi_lock = _SPI_LOCK_BY_BUS.setdefault(spi_bus, threading.Lock())
    return _SHARED_SPI_BY_NODE[spi_node], spi_lock


def _build_adc(adc_id: str, cfg: dict):
    from deep_thrott_code.daq.drivers.adc import ADS124S08

    spi_bus = int(cfg["spi_bus"])
    spi_dev = int(cfg["spi_device"])

    cs_gpio = cfg.get("cs_gpio")
    drdy_gpio = cfg.get("drdy_gpio")
    start_gpio = cfg.get("start_sync_gpio")
    reset_gpio = cfg.get("reset_gpio")

    if cs_gpio is None:
        raise RuntimeError(f"{adc_id}: cs_gpio must be set for manual CS mode.")

    cs_pin = int(cs_gpio)
    drdy_pin = int(drdy_gpio) if drdy_gpio is not None else None
    start_pin = int(start_gpio) if start_gpio is not None else None
    reset_pin = int(reset_gpio) if reset_gpio is not None else None

    max_speed_hz = int(cfg.get("spi_max_speed_hz", 500_000))

    spi, spi_lock = _get_shared_spi(spi_bus, spi_dev, max_speed_hz)

    print(f"\n[{adc_id}] Creating ADC")
    print(f"  SPI bus/dev : {spi_bus}.{spi_dev}")
    print(f"  SPI speed   : {max_speed_hz}")
    print(f"  CS GPIO     : {cs_pin}")
    print(f"  DRDY GPIO   : {drdy_pin}")
    print(f"  START GPIO  : {start_pin}")
    print(f"  RESET GPIO  : {reset_pin}")

    adc = ADS124S08(
        id=adc_id,
        spi=spi,
        spi_lock=spi_lock,
        cs_pin=cs_pin,
        all_cs_pins=_MANUAL_CS_PINS,
        drdy_pin=drdy_pin,
        start_pin=start_pin,
        reset_pin=reset_pin,
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


def _check_one(
    adc_id: str,
    cfg: dict,
    ain: int,
    *,
    gain: int = 1,
    diff: tuple[int, int] | None = None,
    ignore_drdy: bool = False,
) -> int:
    if ignore_drdy and isinstance(cfg, dict):
        cfg = dict(cfg)
        cfg["drdy_gpio"] = None

    adc = _build_adc(adc_id, cfg)

    try:
        adc.enter_command_mode()

        print(f"\n[{adc_id}] Initial register read:")
        print(adc.rreg(0x00, 8))

        time.sleep(0.05)

        _print_register_dump(adc, "--- REGISTER DUMP AFTER STOP/SDATAC ---")

        _spi_write_read_tests(adc)

        _print_register_dump(adc, "--- REGISTER DUMP AFTER WRITE/READBACK TESTS ---")

        gain_i = int(gain)
        if gain_i not in {1, 2, 4, 8, 16, 32, 64, 128}:
            raise ValueError("gain must be one of 1,2,4,8,16,32,64,128")

        print(f"\n[{adc_id}] Configuring ADC...")
        adc.configure_basic(use_internal_ref=False, gain=gain_i)

        print(f"\n[{adc_id}] Sending START command...")
        adc.start()

        time.sleep(0.01)

        _check_drdy_pin(adc_id, adc)

        print(f"\n[{adc_id}] Waiting for DRDY...")
        ok = adc.wait_drdy(0.5)

        print(f"[{adc_id}] DRDY result: {ok}")

        if not ok:
            print(f"\n[{adc_id}] DRDY TIMEOUT")
            return 1

        if diff is None:
            print(f"\n[{adc_id}] Attempting single-ended sample reads...")
        else:
            ainp, ainn = int(diff[0]), int(diff[1])
            print(f"\n[{adc_id}] Attempting differential sample reads AIN{ainp}-AIN{ainn}...")

        for i in range(3):
            try:
                print(f"\n[{adc_id}] Read attempt {i}")

                if diff is None:
                    code = adc.read_raw_single(int(ain), settle_discard=True)
                    volts = _adc_code_to_voltage(int(code), vref=5.0, gain=float(gain_i))
                    print(f"[{adc_id}] AIN{ain} raw code = {code}  V={volts: .6f}")
                else:
                    code = adc.read_raw_diff(int(diff[0]), int(diff[1]), settle_discard=True)
                    volts = _adc_code_to_voltage(int(code), vref=5.0, gain=float(gain_i))
                    print(
                        f"[{adc_id}] AIN{int(diff[0])}-AIN{int(diff[1])} raw code = {code}  Vdiff={volts: .6f}"
                    )

            except TimeoutError as e:
                print(f"[{adc_id}] TIMEOUT: {e}")

            except Exception as e:
                print(f"[{adc_id}] READ FAILED: {e}")

            time.sleep(0.1)

        return 0

    finally:
        adc.close()


def _stream_one(
    adc_id: str,
    cfg: dict,
    ain: int,
    *,
    minutes: float,
    gain: int = 1,
    diff: tuple[int, int] | None = None,
    ignore_drdy: bool = False,
) -> int:
    if ignore_drdy and isinstance(cfg, dict):
        cfg = dict(cfg)
        cfg["drdy_gpio"] = None

    if minutes <= 0:
        raise ValueError("minutes must be > 0")

    adc = _build_adc(adc_id, cfg)

    try:
        adc.enter_command_mode()

        gain_i = int(gain)
        if gain_i not in {1, 2, 4, 8, 16, 32, 64, 128}:
            raise ValueError("gain must be one of 1,2,4,8,16,32,64,128")

        print(f"\n[{adc_id}] Configuring ADC...")
        adc.configure_basic(use_internal_ref=False, gain=gain_i)

        if diff is None:
            print(f"\n[{adc_id}] Streaming single-ended AIN{ain} for {minutes:.2f} minutes...")
        else:
            ainp, ainn = int(diff[0]), int(diff[1])
            print(f"\n[{adc_id}] Streaming differential AIN{ainp}-AIN{ainn} for {minutes:.2f} minutes...")

        print(f"  Conversion assumes vref=5.0 V, gain={gain_i}")

        if diff is None:
            adc.set_inpmux_single(int(ain))
        else:
            adc.set_inpmux_diff(int(diff[0]), int(diff[1]))

        adc.start()

        if not adc.wait_drdy(1.0):
            print(f"[{adc_id}] DRDY TIMEOUT initial")
            return 1

        _ = adc.read_raw_sample()

        t0 = time.perf_counter()
        t_end = t0 + (float(minutes) * 60.0)
        n = 0

        try:
            while True:
                if time.perf_counter() >= t_end:
                    break

                if not adc.wait_drdy(1.0):
                    print(f"[{adc_id}] DRDY TIMEOUT")
                    return 1

                code = adc.read_raw_sample()
                t_samp = time.perf_counter()
                volts = _adc_code_to_voltage(int(code), vref=5.0, gain=float(gain_i))

                print(
                    f"t={t_samp - t0:9.3f}s  code={int(code):8d}  V={volts: .6f}",
                    flush=True,
                )
                n += 1

        except KeyboardInterrupt:
            print(f"\n[{adc_id}] Stopped by user.")

        dt = time.perf_counter() - t0
        if dt > 0:
            print(f"\n[{adc_id}] Done. {n} samples in {dt:.1f}s (~{n / dt:.1f} Hz).")
        else:
            print(f"\n[{adc_id}] Done. {n} samples.")

        return 0

    finally:
        adc.close()


def _close_shared_spi() -> None:
    for spi in _SHARED_SPI_BY_NODE.values():
        try:
            spi.close()
        except Exception:
            pass


def main() -> int:
    _repo_src_on_path()

    ap = argparse.ArgumentParser()

    ap.add_argument("--adc", default=None, help="ADC id, e.g. ADC1/ADC2/ADC3")
    ap.add_argument("--ain", type=int, default=0, help="AIN index to read")
    ap.add_argument(
        "--diff",
        nargs=2,
        type=int,
        default=None,
        metavar=("AINP", "AINN"),
        help="Differential read AINP-AINN.",
    )
    ap.add_argument(
        "--gain",
        type=int,
        default=1,
        help="ADS124S08 PGA gain.",
    )
    ap.add_argument("--all", action="store_true", help="Check all configured ADCs")
    ap.add_argument(
        "--ignore-drdy",
        action="store_true",
        help="Ignore DRDY pin to isolate DRDY wiring/config issues.",
    )
    ap.add_argument(
        "--stream-minutes",
        nargs="?",
        const=15.0,
        default=None,
        type=float,
        help="Continuously read AIN for N minutes.",
    )

    args = ap.parse_args()

    hw = _load_hardware_cfg()
    adcs = hw.get("adcs")

    if not isinstance(adcs, dict) or not adcs:
        print("No 'adcs' section found in hardware.yml")
        return 2

    _setup_gpio(adcs)

    try:
        if args.stream_minutes is not None:
            if args.all:
                print("--stream-minutes cannot be combined with --all")
                return 2

            if not args.adc:
                print("Provide --adc ADC1, or use --all")
                return 2

            cfg = adcs.get(args.adc)

            if not isinstance(cfg, dict):
                print(f"Unknown ADC id: {args.adc}")
                return 2

            return _stream_one(
                args.adc,
                cfg,
                args.ain,
                minutes=float(args.stream_minutes),
                gain=int(args.gain),
                diff=tuple(args.diff) if args.diff is not None else None,
                ignore_drdy=bool(args.ignore_drdy),
            )

        if args.all:
            rc = 0

            for adc_id, cfg in adcs.items():
                if not isinstance(adc_id, str):
                    continue

                if not isinstance(cfg, dict):
                    continue

                rc |= _check_one(
                    adc_id,
                    cfg,
                    args.ain,
                    gain=int(args.gain),
                    diff=tuple(args.diff) if args.diff is not None else None,
                    ignore_drdy=bool(args.ignore_drdy),
                )

            return rc

        if not args.adc:
            print("Provide --adc ADC1, or use --all")
            return 2

        cfg = adcs.get(args.adc)

        if not isinstance(cfg, dict):
            print(f"Unknown ADC id: {args.adc}")
            return 2

        return _check_one(
            args.adc,
            cfg,
            args.ain,
            gain=int(args.gain),
            diff=tuple(args.diff) if args.diff is not None else None,
            ignore_drdy=bool(args.ignore_drdy),
        )

    finally:
        for cs_pin in _MANUAL_CS_PINS:
            try:
                GPIO.output(cs_pin, GPIO.HIGH)
            except Exception:
                pass

        _close_shared_spi()
        GPIO.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())