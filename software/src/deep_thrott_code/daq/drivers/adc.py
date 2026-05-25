#!/usr/bin/env python3

import time
import threading
import RPi.GPIO as GPIO  # type: ignore


class ADS124S08:
    """ADS124S08 driver using caller-managed shared SPI + manual GPIO chip select."""

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
        spi,
        spi_lock,
        cs_pin,
        all_cs_pins,
        reset_pin=None,
        drdy_pin=None,
        start_pin=None,
    ):
        self.id = id
        self.spi = spi
        self._spi_lock = spi_lock or threading.Lock()

        self.cs_pin = int(cs_pin)
        self.all_cs_pins = [int(p) for p in all_cs_pins]

        self.reset_pin = int(reset_pin) if reset_pin is not None else None
        self.drdy_pin = int(drdy_pin) if drdy_pin is not None else None
        self.start_pin = int(start_pin) if start_pin is not None else None

        GPIO.setup(self.cs_pin, GPIO.OUT, initial=GPIO.HIGH)

        if self.reset_pin is not None:
            GPIO.setup(self.reset_pin, GPIO.OUT, initial=GPIO.HIGH)

        if self.start_pin is not None:
            GPIO.setup(self.start_pin, GPIO.OUT, initial=GPIO.HIGH)

        if self.drdy_pin is not None:
            GPIO.setup(self.drdy_pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)

        self._ref_reg_backup = None
        self._idac_enabled = False
        self._cached_pga_reg = None
        self._cached_ref_reg = None
        self._cached_datarate_reg = None

        self._deselect_all()
        time.sleep(0.01)

    def _deselect_all(self):
        for pin in self.all_cs_pins:
            GPIO.output(pin, GPIO.HIGH)

    def _chip_select_asserted(self):
        class _CS:
            def __init__(self, outer: "ADS124S08"):
                self.o = outer

            def __enter__(self):
                self.o._spi_lock.acquire()

                self.o._deselect_all()
                time.sleep(5e-6)

                GPIO.output(self.o.cs_pin, GPIO.LOW)
                time.sleep(5e-6)

                return self

            def __exit__(self, exc_type, exc, tb):
                time.sleep(5e-6)
                GPIO.output(self.o.cs_pin, GPIO.HIGH)
                time.sleep(5e-6)

                self.o._spi_lock.release()
                return False

        return _CS(self)

    def get_drdy_level(self):
        if self.drdy_pin is None:
            return None
        return "HIGH" if GPIO.input(self.drdy_pin) else "LOW"

    def _send_cmd(self, cmd: int) -> None:
        with self._chip_select_asserted():
            self.spi.xfer2([cmd])

    def wreg(self, addr: int, data_bytes: list[int]) -> None:
        n = len(data_bytes)
        with self._chip_select_asserted():
            self.spi.xfer2([0x40 | (addr & 0x1F), n - 1] + list(data_bytes))

    def rreg(self, addr: int, n: int) -> list[int]:
        with self._chip_select_asserted():
            rx = self.spi.xfer2([0x20 | (addr & 0x1F), n - 1] + [0x00] * n)
        return rx[2:]

    def hardware_reset(self) -> None:
        if self.reset_pin is not None:
            GPIO.output(self.reset_pin, GPIO.LOW)
            time.sleep(0.005)
            GPIO.output(self.reset_pin, GPIO.HIGH)
        else:
            self._send_cmd(self.CMD_RESET)

        time.sleep(0.05)

    def start(self) -> None:
        self._send_cmd(self.CMD_START)

    def stop(self) -> None:
        self._send_cmd(self.CMD_STOP)

    def enter_command_mode(self) -> None:
        self.stop()
        self._send_cmd(self.CMD_SDATAC)
        time.sleep(0.01)

    def wait_drdy(self, timeout_s: float = 0.5) -> bool:
        if self.drdy_pin is None:
            time.sleep(timeout_s)
            return True

        t0 = time.perf_counter()
        # The ADS124S08 can convert as fast as 2000-4000 SPS, so a coarse
        # 500 us polling sleep can miss entire ready windows and crush
        # effective throughput. Keep the loop tight and only yield briefly.
        spin_budget_s = 0.0002
        poll_sleep_s = 0.00002

        while (time.perf_counter() - t0) < timeout_s:
            if GPIO.input(self.drdy_pin) == GPIO.LOW:
                return True

            if (time.perf_counter() - t0) >= spin_budget_s:
                time.sleep(poll_sleep_s)

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
        desired_pga = 0x00
        if gain == 1:
            desired_pga = 0x00
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

            desired_pga = (1 << 3) | gain_map[gain]

        if self._cached_pga_reg != desired_pga:
            self.wreg(self.REG_PGA, [desired_pga])
            self._cached_pga_reg = desired_pga

        if use_internal_ref:
            desired_ref = 0x39
            if self._cached_ref_reg != desired_ref:
                self.wreg(self.REG_REF, [desired_ref])
                self._cached_ref_reg = desired_ref

        if data_rate is not None:
            desired_datarate = int(data_rate) & 0xFF
            if self._cached_datarate_reg != desired_datarate:
                self.wreg(self.REG_DATARATE, [desired_datarate])
                self._cached_datarate_reg = desired_datarate

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
        self._cached_ref_reg = cur

        if self._ref_reg_backup is None:
            self._ref_reg_backup = cur

        cur = (cur & ~0x0C) | 0x08
        cur = (cur & ~0x03) | 0x01

        self.wreg(self.REG_REF, [cur])
        self._cached_ref_reg = cur

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
            self._cached_ref_reg = self._ref_reg_backup
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
        self.stop()
        self.set_inpmux_single(ainp)
        self.start()

        if not self.wait_drdy(0.5):
            raise TimeoutError(f"{self.id}: DRDY timeout after MUX change")

        _ = self.read_raw_sample()

        if settle_discard:
            if not self.wait_drdy(0.5):
                raise TimeoutError(f"{self.id}: DRDY timeout after settle discard")

        return self.read_raw_sample()

    def read_raw_diff(
        self,
        ainp: int,
        ainn: int,
        settle_discard: bool = True,
    ) -> int:
        self.stop()
        self.set_inpmux_diff(ainp, ainn)
        self.start()

        if not self.wait_drdy(0.5):
            raise TimeoutError(f"{self.id}: DRDY timeout after MUX change")

        _ = self.read_raw_sample()

        if settle_discard:
            if not self.wait_drdy(0.5):
                raise TimeoutError(f"{self.id}: DRDY timeout after settle discard")

        return self.read_raw_sample()

    def close(self) -> None:
        try:
            self._deselect_all()
        except Exception:
            pass

        try:
            GPIO.output(self.cs_pin, GPIO.HIGH)
        except Exception:
            pass