#!/usr/bin/env python3
"""ADS124S08 smoke test with extra diagnostics."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path


# One lock per SPI bus to prevent interleaved transfers.
_SPI_LOCK_BY_BUS: dict[int, threading.Lock] = {}


def _adc_code_to_voltage(code: int, *, vref: float = 5.0, gain: float = 1.0) -> float:
    """Convert a 24-bit signed ADS124S08 code to volts.

    Assumes the simple full-scale model used elsewhere in this repo.
    """

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
    print(f"  START GPIO  : {start_pin}")

    spi_lock = _SPI_LOCK_BY_BUS.setdefault(spi_bus, threading.Lock())

    adc = ADS124S08(
        id=adc_id,
        spi_bus=spi_bus,
        spi_dev=spi_dev,
        spi_lock=spi_lock,
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
            print("Most likely causes now:")
            print("  - SPI data path issue: MOSI/MISO/SCLK")
            print("  - Wrong SPI mode")
            print("  - DOUT/DRDY confusion")
            print("  - ADC DOUT not connected to Pi MISO")
            print("  - ADC not actually receiving START command")
            return 1

        if diff is None:
            print(f"\n[{adc_id}] Attempting single-ended sample reads...")
        else:
            ainp, ainn = int(diff[0]), int(diff[1])
            print(f"\n[{adc_id}] Attempting differential sample reads (AIN{ainp}-AIN{ainn})...")

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
                        f"[{adc_id}] AIN{int(diff[0])}-AIN{int(diff[1])} raw code = {code}  Vdiff={volts: .6f}")

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
        adc.stop()
        adc._send_cmd(adc.CMD_SDATAC)
        time.sleep(0.01)

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

        # Discard first conversion after a MUX change for settling.
        if not adc.wait_drdy(1.0):
            print(f"[{adc_id}] DRDY TIMEOUT (initial)")
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

                # Print monotonically increasing elapsed time for easy plotting.
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
        help="Differential read AINP-AINN (useful for load cells).",
    )
    ap.add_argument(
        "--gain",
        type=int,
        default=1,
        help="ADS124S08 PGA gain (1,2,4,8,16,32,64,128).",
    )
    ap.add_argument("--all", action="store_true", help="Check all configured ADCs")
    ap.add_argument(
        "--ignore-drdy",
        action="store_true",
        help="Ignore DRDY pin (treat as unconfigured) to isolate DRDY wiring/config issues.",
    )

    ap.add_argument(
        "--stream-minutes",
        nargs="?",
        const=15.0,
        default=None,
        type=float,
        help="Continuously read AIN and print raw code + volts for N minutes (default: 15).",
    )

    args = ap.parse_args()

    hw = _load_hardware_cfg()
    adcs = hw.get("adcs")

    if not isinstance(adcs, dict) or not adcs:
        print("No 'adcs' section found in hardware.yml")
        return 2

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


if __name__ == "__main__":
    raise SystemExit(main())