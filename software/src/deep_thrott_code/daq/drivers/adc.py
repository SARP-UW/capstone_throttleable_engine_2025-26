#!/usr/bin/env python3
import os
import time
import spidev
import gpiod
from gpiod.line import Direction, Value


class ADS124S08:
    """Low-level ADS124S08 driver for Raspberry Pi + libgpiod v2."""

    REG_INPMUX = 0x02
    REG_PGA = 0x03
    REG_DATARATE = 0x04
    REG_REF = 0x05
    REG_IDACMAG = 0x06
    REG_IDACMUX = 0x07

    CMD_RESET = 0x06
    CMD_START = 0x08
    CMD_STOP = 0x0A
    CMD_RDATA = 0x12
    CMD_RDATAC = 0x14
    CMD_SDATAC = 0x16
    CMD_SFOCAL = 0x19

    AINCOM_CODE = 0x0C
    RREF_OHMS = 5600.0

    _IDAC_CURRENT_MAP_UA = {
        10: 0x01,
        50: 0x02,
        100: 0x03,
        250: 0x04,
        500: 0x05,
        750: 0x06,
        1000: 0x07,
        1500: 0x08,
        2000: 0x09,
    }

    def __init__(
        self,
        id,
        spi_bus,
        spi_dev,
        cs_pin=None,
        gpiochip="/dev/gpiochip0",
        reset_pin=None,
        drdy_pin=None,
        start_pin=None,
        max_speed_hz=10_000,
        spi_mode=0b00,
    ):
        devpath = f"/dev/spidev{spi_bus}.{spi_dev}"
        if not os.path.exists(devpath):
            raise RuntimeError(f"{devpath} not found. Enable SPI and/or correct bus/dev.")

        self.id = id
        self.spi_bus = spi_bus
        self.spi_dev = spi_dev
        self.cs_pin = cs_pin
        self.reset_pin = reset_pin
        self.start_pin = None
        self.drdy_pin = drdy_pin

        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_dev)
        self.spi.mode = spi_mode
        self.spi.max_speed_hz = max_speed_hz
        self.spi.bits_per_word = 8

        if cs_pin is not None:
            try:
                self.spi.no_cs = True
            except Exception:
                pass

        self.chip = gpiod.Chip(gpiochip)

        self._req_out = None
        out_cfg = {}

        if cs_pin is not None:
            out_cfg[cs_pin] = gpiod.LineSettings(
                direction=Direction.OUTPUT,
                active_low=True,
                output_value=Value.INACTIVE,
            )

        if reset_pin is not None:
            out_cfg[reset_pin] = gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=Value.ACTIVE,
            )

        if out_cfg:
            self._req_out = self.chip.request_lines(
                config=out_cfg,
                consumer="ads124_out",
            )

        self._req_in = None
        if drdy_pin is not None:
            self._req_in = self.chip.request_lines(
                config={
                    drdy_pin: gpiod.LineSettings(
                        direction=Direction.INPUT,
                    )
                },
                consumer="ads124_in",
            )

        self._ref_reg_backup = None
        self._idac_enabled = False

        time.sleep(0.01)

    def _chip_select_asserted(self):
        class _CS:
            def __init__(self, outer: "ADS124S08"):
                self._outer = outer

            def __enter__(self):
                o = self._outer
                if o._req_out is not None and o.cs_pin is not None:
                    o._req_out.set_value(o.cs_pin, Value.ACTIVE)
                return self

            def __exit__(self, exc_type, exc, tb):
                o = self._outer
                if o._req_out is not None and o.cs_pin is not None:
                    o._req_out.set_value(o.cs_pin, Value.INACTIVE)
                return False

        return _CS(self)

    def get_drdy_level(self):
        if self._req_in is None or self.drdy_pin is None:
            return None

        val = self._req_in.get_value(self.drdy_pin)

        if val == Value.ACTIVE:
            return "HIGH"

        return "LOW"

    def _send_cmd(self, cmd: int) -> None:
        with self._chip_select_asserted():
            self.spi.xfer2([cmd])

    def wreg(self, addr: int, data_bytes: list[int]) -> None:
        n = len(data_bytes)
        with self._chip_select_asserted():
            self.spi.xfer2([0x40 | (addr & 0x1F), (n - 1)] + list(data_bytes))

    def rreg(self, addr: int, n: int) -> list[int]:
        with self._chip_select_asserted():
            rx = self.spi.xfer2([0x20 | (addr & 0x1F), (n - 1)] + [0x00] * n)
        return rx[2:]

    def hardware_reset(self) -> None:
        if self._req_out is not None and self.reset_pin is not None:
            self._req_out.set_value(self.reset_pin, Value.INACTIVE)
            time.sleep(0.005)
            self._req_out.set_value(self.reset_pin, Value.ACTIVE)
        else:
            self._send_cmd(self.CMD_RESET)

        time.sleep(0.05)

    def start(self) -> None:
        self._send_cmd(self.CMD_START)

    def stop(self) -> None:
        self._send_cmd(self.CMD_STOP)

    def wait_drdy(self, timeout_s: float = 0.5) -> bool:
        if self._req_in is None or self.drdy_pin is None:
            time.sleep(timeout_s)
            return True

        t0 = time.perf_counter()

        while (time.perf_counter() - t0) < timeout_s:
            if self._req_in.get_value(self.drdy_pin) == Value.INACTIVE:
                return True

            time.sleep(0.0005)

        return False

    def read_raw_sample(self) -> int:
        with self._chip_select_asserted():
            rx = self.spi.xfer2([self.CMD_RDATA, 0x00, 0x00, 0x00])

        b2, b1, b0 = rx[1], rx[2], rx[3]
        code = (b2 << 16) | (b1 << 8) | b0

        if code & 0x800000:
            code -= 1 << 24

        return code

    def configure_basic(
        self,
        use_internal_ref: bool = False,
        gain: int = 1,
        data_rate=None,
    ) -> None:
        if gain == 1:
            self.wreg(self.REG_PGA, [0x00])
        else:
            gain_map = {
                1: 0,
                2: 1,
                4: 2,
                8: 3,
                16: 4,
                32: 5,
                64: 6,
                128: 7,
            }

            if gain not in gain_map:
                raise ValueError("gain must be one of 1,2,4,8,16,32,64,128")

            self.wreg(self.REG_PGA, [(1 << 3) | gain_map[gain]])

        if use_internal_ref:
            self.wreg(self.REG_REF, [0x39])

        if data_rate is not None:
            self.wreg(self.REG_DATARATE, [data_rate])

    def _idac_current_code(self, current_ua: int) -> int:
        current_ua = int(round(current_ua))

        try:
            return self._IDAC_CURRENT_MAP_UA[current_ua]
        except KeyError:
            allowed = ", ".join(str(u) for u in sorted(self._IDAC_CURRENT_MAP_UA.keys()))
            raise ValueError(
                f"IDAC current must be one of {allowed} µA "
                f"(got {current_ua} µA)"
            ) from None

    def _set_ref_for_rtd(self) -> None:
        cur = self.rreg(self.REG_REF, 1)[0]

        if self._ref_reg_backup is None:
            self._ref_reg_backup = cur

        cur = (cur & ~0x0C) | 0x08
        cur = (cur & ~0x03) | 0x01

        self.wreg(self.REG_REF, [cur])

    def configure_idac_outputs(
        self,
        current_ua: int,
        idac1_ain: int,
        idac2_ain: int,
    ) -> None:
        def _ain_to_code(ain: int) -> int:
            if not (0 <= ain <= 11):
                raise ValueError("AIN index must be in 0..11")
            return ain & 0x0F

        mag_code = self._idac_current_code(current_ua)
        idac1_code = _ain_to_code(idac1_ain)
        idac2_code = _ain_to_code(idac2_ain)

        mux_val = (idac2_code << 4) | idac1_code

        self.wreg(self.REG_IDACMAG, [mag_code])
        self.wreg(self.REG_IDACMUX, [mux_val])

        self._idac_enabled = True

    def enable_rtd_mode(
        self,
        current_ua: int = 500,
        idac1_ain: int = 5,
        idac2_ain: int = 3,
    ) -> None:
        self._set_ref_for_rtd()

        self.configure_idac_outputs(
            current_ua=current_ua,
            idac1_ain=idac1_ain,
            idac2_ain=idac2_ain,
        )

    def disable_rtd_mode(self) -> None:
        self.wreg(self.REG_IDACMAG, [0x00])
        self.wreg(self.REG_IDACMUX, [0xFF])

        self._idac_enabled = False

        if self._ref_reg_backup is not None:
            self.wreg(self.REG_REF, [self._ref_reg_backup])
            self._ref_reg_backup = None

    def set_inpmux_single(self, ainp: int) -> None:
        if not (0 <= ainp <= 11):
            raise ValueError("ainp must be 0..11")

        val = ((ainp & 0x0F) << 4) | (self.AINCOM_CODE & 0x0F)

        self.wreg(self.REG_INPMUX, [val])

    def set_inpmux_diff(self, ainp: int, ainn: int) -> None:
        if not (0 <= ainp <= 11):
            raise ValueError("ainp must be 0..11")

        if not (0 <= ainn <= 11):
            raise ValueError("ainn must be 0..11")

        val = ((ainp & 0x0F) << 4) | (ainn & 0x0F)

        self.wreg(self.REG_INPMUX, [val])

    def read_raw_single(
        self,
        ainp: int,
        settle_discard: bool = True,
    ) -> int:
        self.set_inpmux_single(ainp)

        self.start()

        if not self.wait_drdy(0.5):
            raise TimeoutError("DRDY timeout after MUX change")

        _ = self.read_raw_sample()

        if settle_discard:
            if not self.wait_drdy(0.5):
                raise TimeoutError("DRDY timeout after settle discard")

        return self.read_raw_sample()

    def read_raw_diff(
        self,
        ainp: int,
        ainn: int,
        settle_discard: bool = True,
    ) -> int:
        self.set_inpmux_diff(ainp, ainn)

        self.start()

        if not self.wait_drdy(0.5):
            raise TimeoutError("DRDY timeout after MUX change")

        _ = self.read_raw_sample()

        if settle_discard:
            if not self.wait_drdy(0.5):
                raise TimeoutError("DRDY timeout after settle discard")

        return self.read_raw_sample()

    def close(self) -> None:
        try:
            self.spi.close()
        except Exception:
            pass