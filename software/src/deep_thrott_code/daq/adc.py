# #!/usr/bin/env python3
# import os
# import time
# import math
# # import spidev
# # import gpiod
# # from gpiod.line import Direction, Value


# class ADS124S08:
#     """Minimal ADS124S08 driver for Raspberry Pi (SPI mode 1) + libgpiod v2."""

#     # --- Register addresses (subset) ---
#     REG_INPMUX = 0x02
#     REG_PGA = 0x03
#     REG_DATARATE = 0x04
#     REG_REF = 0x05
#     REG_IDACMAG = 0x06  # Excitation Current Register 1 (IDACMAG)
#     REG_IDACMUX = 0x07  # Excitation Current Register 2 (IDACMUX)

#     # --- Commands (subset) ---
#     CMD_RESET = 0x06
#     CMD_START = 0x08
#     CMD_STOP = 0x0A
#     CMD_RDATA = 0x12
#     CMD_RDATAC = 0x14
#     CMD_SDATAC = 0x16
#     CMD_SFOCAL = 0x19  # self offset calibration (optional)

#     AINCOM_CODE = 0x0C  # AINCOM value used in INPMUX (lower nibble)

#     # --- RTD / IDAC-related constants ---
#     RREF_OHMS = 5600.0

#     # In microamps from 10 µA - 2000 µA.
#     _IDAC_CURRENT_MAP_UA = {
#         10: 0x01,
#         50: 0x02,
#         100: 0x03,
#         250: 0x04,
#         500: 0x05,
#         750: 0x06,
#         1000: 0x07,
#         1500: 0x08,
#         2000: 0x09,
#     }

#     def __init__(self, id, spi_bus, spi_dev, gpiochip="/dev/gpiochip0", reset_pin=None, drdy_pin=None, start_pin=None, max_speed_hz=100_000):

#         # --- SPI setup ---
#         devpath = f"/dev/spidev{spi_bus}.{spi_dev}"
#         if not os.path.exists(devpath):
#             raise RuntimeError(f"{devpath} not found. Enable SPI and/or correct bus/dev.")
#         self.id = id
#         self.spi = spidev.SpiDev()
#         self.spi.open(spi_bus, spi_dev)  # (0,0) or (0,1)
#         self.spi.mode = 0b01  # ADS124S08 requires mode 1
#         self.spi.max_speed_hz = max_speed_hz
#         self.spi.bits_per_word = 8

#         # --- GPIO (libgpiod v2) ---
#         self.reset_pin = reset_pin
#         self.start_pin = start_pin
#         self.drdy_pin = drdy_pin

#         self.chip = gpiod.Chip(gpiochip)

#         # request outputs
#         self._req_out = None
#         out_cfg = {}
#         if reset_pin is not None:
#             out_cfg[reset_pin] = gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)  # RESET high
#         if start_pin is not None:
#             out_cfg[start_pin] = gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)  # START low
#         if out_cfg:
#             self._req_out = self.chip.request_lines(config=out_cfg, consumer="ads124_out")

#         # request input (DRDY)
#         self._req_in = None
#         if drdy_pin is not None:
#             self._req_in = self.chip.request_lines(config={drdy_pin: gpiod.LineSettings(direction=Direction.INPUT)}, consumer="ads124_in")

#         time.sleep(0.005)
#         self._ref_reg_backup = None  # may not need, maybe delete later
#         self._idac_enabled = False  # may not need, maybe delete later

#     # ----------------- Low-level helpers -----------------
#     def _send_cmd(self, cmd):
#         self.spi.xfer2([cmd])

#     def wreg(self, addr, data_bytes):
#         """Write n bytes starting at register 'addr'."""
#         n = len(data_bytes)
#         self.spi.xfer2([0x40 | (addr & 0x1F), (n - 1)] + list(data_bytes))

#     def rreg(self, addr, n):
#         """Read n bytes starting at register 'addr' -> returns list of bytes."""
#         rx = self.spi.xfer2([0x20 | (addr & 0x1F), (n - 1)] + [0x00] * n)
#         # response: [cmd, count, <n bytes>]
#         return rx[2:]

#     def hardware_reset(self):
#         """Toggle RESET pin if provided; otherwise send RESET command."""
#         if self._req_out and self.reset_pin is not None:
#             self._req_out.set_value(self.reset_pin, Value.INACTIVE)  # RESET low
#             time.sleep(0.001)
#             self._req_out.set_value(self.reset_pin, Value.ACTIVE)  # RESET high
#         else:
#             self._send_cmd(self.CMD_RESET)
#         time.sleep(0.005)

#     def start(self):
#         self._send_cmd(self.CMD_START)

#     def stop(self):
#         self._send_cmd(self.CMD_STOP)

#     def wait_drdy(self, timeout_s=0.2):
#         """Wait for DRDY low (active-low). If no DRDY line, just sleep."""
#         if self._req_in is None or self.drdy_pin is None:
#             time.sleep(timeout_s)
#             return True
#         t0 = time.time()
#         while (time.time() - t0) < timeout_s:
#             if self._req_in.get_value(self.drdy_pin) == Value.INACTIVE:
#                 return True
#         return False

#     def read_raw_sample(self):
#         """Send RDATA and read 24-bit signed result."""
#         rx = self.spi.xfer2([self.CMD_RDATA, 0x00, 0x00, 0x00])
#         b2, b1, b0 = rx[1], rx[2], rx[3]
#         code = (b2 << 16) | (b1 << 8) | b0
#         # sign-extend 24-bit
#         if code & 0x800000:
#             code -= 1 << 24
#         return code

#     # ----------------- Config helpers -----------------
#     def configure_basic(self, use_internal_ref=False, gain=1, data_rate=None):
#         """
#         Basic sane setup:
#         - Optionally enable/select internal 2.5V reference.
#         - Set PGA bypass/gain.
#         - (Optional) set data rate if provided.
#         """
#         # PGA register
#         if gain == 1:
#             # PGA bypassed (gain=1)
#             self.wreg(self.REG_PGA, [0x00])
#         else:
#             gain_map = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6, 128: 7}
#             if gain not in gain_map:
#                 raise ValueError("gain must be one of 1,2,4,8,16,32,64,128")
#             # Enable PGA, set gain code
#             self.wreg(self.REG_PGA, [(1 << 3) | gain_map[gain]])

#         # Reference register
#         if use_internal_ref:
#             # Turn on internal 2.5V reference and select it.
#             # Also keep external ref buffers disabled.
#             # (Value chosen to match common TI app note settings.)
#             self.wreg(self.REG_REF, [0x39])

#         # Data rate (optional): if you know the code you want, write it here.
#         if data_rate is not None:
#             self.wreg(self.REG_DATARATE, [data_rate])

#     # ----------------- RTD / IDAC helpers -----------------
#     def _idac_current_code(self, current_ua: int) -> int:
#         """
#         Map desired IDAC current (µA) to the IMAG code used in IDACMAG.

#         Valid currents (µA): 10, 50, 100, 250, 500, 750, 1000, 1500, 2000.
#         """
#         # Accept floats like 500.0
#         current_ua = int(round(current_ua))
#         try:
#             return self._IDAC_CURRENT_MAP_UA[current_ua]
#         except KeyError:
#             allowed = ", ".join(str(u) for u in sorted(self._IDAC_CURRENT_MAP_UA.keys()))
#             raise ValueError(f"IDAC current must be one of {allowed} µA (got {current_ua} µA)") from None

#     def _set_ref_for_rtd(self) -> None:
#         """
#         Select the internal 2.5 V reference as the ADC reference and enable it.
#         IDACs require the internal reference to be on.

#         The RTD resistance is computed via software ratiometric: two
#         differential reads (RTD voltage and Rref voltage) are taken against the
#         same internal reference, then their ratio is used.  This avoids needing
#         Rref on a hardware REFP/REFN pin.
#         """
#         cur = self.rreg(self.REG_REF, 1)[0]
#         if self._ref_reg_backup is None:
#             self._ref_reg_backup = cur

#         # REFSEL bits [3:2] = 10 → internal 2.5 V reference
#         cur = (cur & ~0x0C) | 0x08
#         # REFCON bits [1:0] = 01 → internal reference on (required for IDACs)
#         cur = (cur & ~0x03) | 0x01

#         self.wreg(self.REG_REF, [cur])

#     def configure_idac_outputs(self, current_ua: int, idac1_ain: int, idac2_ain: int) -> None:
#         """
#         Route IDAC1 and IDAC2 to the specified AIN pins and set the current.

#         Parameters
#         ----------
#         current_ua : int or float
#             Desired IDAC magnitude in microamps. Must be one of:
#             10, 50, 100, 250, 500, 750, 1000, 1500, 2000.
#         idac1_ain : int
#             AIN number (0..11) to drive with IDAC1.
#         idac2_ain : int
#             AIN number (0..11) to drive with IDAC2.
#         """
#         # Map current → IMAG bits
#         mag_code = self._idac_current_code(current_ua)

#         def _ain_to_code(ain: int) -> int:
#             if not (0 <= ain <= 11):
#                 raise ValueError("AIN index must be in 0..11")
#             # In IDACMUX, AIN0..AIN11 map to codes 0x0..0xB for each nibble. :contentReference[oaicite:5]{index=5}
#             return ain & 0x0F

#         idac1_code = _ain_to_code(idac1_ain)  # low nibble (IDAC1)
#         idac2_code = _ain_to_code(idac2_ain)  # high nibble (IDAC2)
#         mux_val = (idac2_code << 4) | idac1_code

#         # Program IDAC magnitude and routing
#         self.wreg(self.REG_IDACMAG, [mag_code])
#         self.wreg(self.REG_IDACMUX, [mux_val])
#         self._idac_enabled = True

#     def enable_rtd_mode(
#         self,
#         current_ua: int = 500,
#         idac1_ain: int = 5,
#         idac2_ain: int = 3,
#     ) -> None:
#         """
#         Enable RTD excitation: switch to internal 2.5 V reference (needed for
#         IDAC operation) and route IDAC currents to the specified pins.

#         The caller is responsible for reading both the RTD and Rref voltages
#         differentially and computing the ratio in software.
#         """
#         self._set_ref_for_rtd()
#         self.configure_idac_outputs(
#             current_ua=current_ua,
#             idac1_ain=idac1_ain,
#             idac2_ain=idac2_ain,
#         )

#     def disable_rtd_mode(self) -> None:
#         """
#         Turn off IDAC outputs and restore the REF register back to whatever
#         it was before the first call to enable_rtd_mode().
#         """
#         # Turn IDACs off:
#         #   IDACMAG = 0 → IMAG = off
#         #   IDACMUX = 0xFF → IDAC1_OFF (0x0F) | IDAC2_OFF (0xF0) :contentReference[oaicite:6]{index=6}
#         self.wreg(self.REG_IDACMAG, [0x00])
#         self.wreg(self.REG_IDACMUX, [0xFF])
#         self._idac_enabled = False

#         # Restore original REF register if we changed it
#         if self._ref_reg_backup is not None:
#             self.wreg(self.REG_REF, [self._ref_reg_backup])
#             self._ref_reg_backup = None

#     def set_inpmux_single(self, ainp):
#         """AINp = ainp (0..11), AINn = AINCOM."""
#         if not (0 <= ainp <= 11):
#             raise ValueError("ainp must be 0..11")
#         val = ((ainp & 0x0F) << 4) | (self.AINCOM_CODE & 0x0F)
#         self.wreg(self.REG_INPMUX, [val])

#     def set_inpmux_diff(self, ainp, ainn):
#         """AINp = ainp (0..11), AINn = ainn (0..11) — true differential."""
#         if not (0 <= ainp <= 11):
#             raise ValueError("ainp must be 0..11")
#         if not (0 <= ainn <= 11):
#             raise ValueError("ainn must be 0..11")
#         val = ((ainp & 0x0F) << 4) | (ainn & 0x0F)
#         self.wreg(self.REG_INPMUX, [val])

#     @staticmethod
#     def code_to_volts(code, vref=5, gain=1):
#         """Convert 24-bit code to volts for bipolar transfer: ±Vref/gain."""
#         FS = (1 << 23) - 1  # 0x7FFFFF
#         return (code / FS) * (vref / gain)

#     # ----------------- Convenience reads -----------------
#     def read_voltage_single(self, ainp, vref=5, gain=1, settle_discard=True):
#         """
#         Set MUX to AINp vs AINCOM, wait for DRDY, optionally discard first sample
#         after mux change, then read and return (code, volts).
#         """
#         self.set_inpmux_single(ainp)
#         # Wait for a conversion with the new MUX; discard the first sample to settle
#         if not self.wait_drdy(0.5):
#             raise TimeoutError("DRDY timeout after MUX change")
#         first = self.read_raw_sample()
#         if settle_discard:
#             if not self.wait_drdy(0.5):
#                 raise TimeoutError("DRDY timeout (settle discard)")
#         code = self.read_raw_sample()
#         volts = self.code_to_volts(code, vref=vref, gain=gain)
#         return volts

#     def read_raw_diff(self, ainp, ainn, settle_discard=True):
#         """
#         Differential read: set MUX to AINp vs AINn, wait for DRDY,
#         optionally discard first sample, then return raw 24-bit signed code.
#         """
#         self.set_inpmux_diff(ainp, ainn)
#         if not self.wait_drdy(0.5):
#             raise TimeoutError("DRDY timeout after MUX change")
#         self.read_raw_sample()
#         if settle_discard:
#             if not self.wait_drdy(0.5):
#                 raise TimeoutError("DRDY timeout (settle discard)")
#         return self.read_raw_sample()

#     def read_voltage_full(self, vref=5, gain=1):
#         voltages = []
#         skip_ains = (3, 5, 6, 7)  # skip ain3 and ain5 as IDAC lines

#         for i in range(12):  # ain0 through ain11
#             if i in skip_ains:
#                 continue
#             try:
#                 volts = self.read_voltage_single(i, vref=vref, gain=gain, settle_discard=True)
#                 voltages.append(round(volts, 4))  # remove round later
#             except Exception as e:
#                 print(f"Error reading ADC{self.id} AIN{i}: {e}")

#         return voltages
    

#     def close(self):
#         try:
#             self.spi.close()
#         except Exception:
#             pass