"""Sensor definitions and helpers.

This module is the single canonical place for sensor implementations.
All sensors (simulated and hardware-backed) share a common interface:

- read_raw_sample() -> RawSample  (producer thread)
- convert_raw_sample_to_sample(raw) -> Sample  (consumer thread)

The current DAQ harness uses the simulated sensors by default.
"""

from __future__ import annotations

import math
import random
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .. import config
from ..services.sample import RawSample, Sample


class Sensor(ABC):
    """Base class for all sensors used by the DAQ loops."""

    name: str

    @abstractmethod
    def read_raw_sample(self) -> RawSample:
        raise NotImplementedError

    @abstractmethod
    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        raise NotImplementedError

    def read(self) -> Sample:
        """Convenience method: read + convert (not used by threaded loops)."""
        return self.convert_raw_sample_to_sample(self.read_raw_sample())


def _adc_code_to_voltage(code: int, *, vref: float = 5.0, gain: float = 1.0) -> float:
    """Convert a 24-bit signed ADC code to a voltage.

    Matches the simple full-scale model used by the simulated sensors.
    """
    fs_code = (1 << 23) - 1
    full_scale = float(vref) / float(gain) if gain else float(vref)
    return (float(code) / fs_code) * full_scale


# ------------------------- Simulated sensors -------------------------


class SimulatedPressureSensor(Sensor):
    def __init__(
        self,
        name: str,
        *,
        offset: float = 200.0,
        amplitude: float = 20.0,
        frequency_hz: float = 0.2,
        step_at_s: float = 3.0,
        step_psi: float = 0.0,
        v_min: float = 0.5,
        v_max: float = 4.5,
        p_min: float = 0.0,
        p_max: float = 1000.0,
        adc_vref: float = 5.0,
        adc_gain: float = 1.0,
        noise_std_psi: float = 1.5,
        seed: int = 0,
        channel: int = 0,
    ):
        self.name = str(name)
        self.channel = int(channel)

        self.offset = float(offset)
        self.amplitude = float(amplitude)
        self.frequency_hz = float(frequency_hz)
        self.step_at_s = float(step_at_s)
        self.step_psi = float(step_psi)
        self.noise_std_psi = float(noise_std_psi)
        self._rng = random.Random(int(seed))

        self.v_min = float(v_min)
        self.v_max = float(v_max)
        self.p_min = float(p_min)
        self.p_max = float(p_max)
        self.v_span = self.v_max - self.v_min
        self.p_span = self.p_max - self.p_min

        self.adc_vref = float(adc_vref)
        self.adc_gain = float(adc_gain)

        self._t0 = time.perf_counter()

    def _t(self, t_mono: float) -> float:
        return t_mono - self._t0

    def pressure_profile(self, t_s: float) -> float:
        p = self.offset + self.amplitude * math.sin(2.0 * math.pi * self.frequency_hz * t_s)
        if t_s > self.step_at_s:
            p += self.step_psi
        if self.noise_std_psi:
            p += self._rng.gauss(0.0, self.noise_std_psi)
        return p

    def pressure_to_voltage(self, pressure_psi: float) -> float:
        if self.p_span == 0:
            return self.v_min
        frac = (pressure_psi - self.p_min) / self.p_span
        frac = max(0.0, min(1.0, frac))
        return self.v_min + frac * self.v_span

    def voltage_to_pressure(self, voltage_v: float) -> float:
        if self.v_span == 0:
            return self.p_min
        frac = (voltage_v - self.v_min) / self.v_span
        return self.p_min + frac * self.p_span

    def voltage_to_adc_code(self, voltage_v: float) -> int:
        fs_code = (1 << 23) - 1
        full_scale = self.adc_vref / self.adc_gain if self.adc_gain else self.adc_vref
        voltage_v = max(-full_scale, min(full_scale, voltage_v))
        code = int(round((voltage_v / full_scale) * fs_code))
        return max(-(1 << 23), min((1 << 23) - 1, code))

    def adc_code_to_voltage(self, code: int) -> float:
        return _adc_code_to_voltage(code, vref=self.adc_vref, gain=self.adc_gain)

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        p = self.pressure_profile(self._t(t_mono))
        v = self.pressure_to_voltage(p)
        code = self.voltage_to_adc_code(v)

        return RawSample(
            sensor_name=self.name,
            sensor_kind="pressure",
            conversion_type="sim_pressure",
            channel=self.channel,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=code,
        )

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code = int(raw_sample.raw_count)
        voltage = self.adc_code_to_voltage(code)
        pressure = self.voltage_to_pressure(voltage)

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="pressure",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=code,
            value=float(pressure),
            units="psi",
            V_diff_1=voltage,
            source="simulated",
        )


class SimulatedLoadCellSensor(Sensor):
    def __init__(
        self,
        name: str,
        *,
        max_load_n: float = 1000.0,
        offset_n: float = 0.0,
        amplitude_n: float = 200.0,
        frequency_hz: float = 0.5,
        step_at_s: float = 3.0,
        step_n: float = 0.0,
        v_common: float = 2.5,
        v_diff_fs: float = 0.01,
        adc_vref: float = 5.0,
        adc_gain: float = 1.0,
        noise_std_n: float = 2.0,
        seed: int = 1,
        channel: int = 0,
    ):
        self.name = str(name)
        self.channel = int(channel)

        self.max_load_n = float(max_load_n)
        self.offset_n = float(offset_n)
        self.amplitude_n = float(amplitude_n)
        self.frequency_hz = float(frequency_hz)
        self.step_at_s = float(step_at_s)
        self.step_n = float(step_n)
        self.noise_std_n = float(noise_std_n)
        self._rng = random.Random(int(seed))

        self.v_common = float(v_common)
        self.v_diff_fs = float(v_diff_fs)
        self.adc_vref = float(adc_vref)
        self.adc_gain = float(adc_gain)

        self._t0 = time.perf_counter()

    def _t(self, t_mono: float) -> float:
        return t_mono - self._t0

    def force_profile_n(self, t_s: float) -> float:
        f = self.offset_n + self.amplitude_n * math.sin(2.0 * math.pi * self.frequency_hz * t_s)
        if t_s > self.step_at_s:
            f += self.step_n
        if self.noise_std_n:
            f += self._rng.gauss(0.0, self.noise_std_n)
        return f

    def _force_to_vdiff(self, force_n: float) -> float:
        if self.max_load_n == 0:
            return 0.0
        ratio = force_n / self.max_load_n
        return ratio * self.v_diff_fs

    def voltage_to_adc_code(self, voltage_v: float) -> int:
        fs_code = (1 << 23) - 1
        full_scale = self.adc_vref / self.adc_gain if self.adc_gain else self.adc_vref
        voltage_v = max(-full_scale, min(full_scale, voltage_v))
        code = int(round((voltage_v / full_scale) * fs_code))
        return max(-(1 << 23), min((1 << 23) - 1, code))

    def adc_code_to_voltage(self, code: int) -> float:
        return _adc_code_to_voltage(code, vref=self.adc_vref, gain=self.adc_gain)

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        force_n = self.force_profile_n(self._t(t_mono))
        vdiff = self._force_to_vdiff(force_n)
        v_plus = self.v_common + (vdiff / 2.0)
        v_minus = self.v_common - (vdiff / 2.0)
        code_plus = self.voltage_to_adc_code(v_plus)
        code_minus = self.voltage_to_adc_code(v_minus)
        code_diff = int(code_plus - code_minus)

        return RawSample(
            sensor_name=self.name,
            sensor_kind="load_cell",
            conversion_type="sim_loadcell",
            channel=self.channel,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=code_diff,
            raw_diff_1=code_plus,
            raw_diff_2=code_minus,
        )

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code_plus = raw_sample.raw_diff_1
        code_minus = raw_sample.raw_diff_2

        if code_plus is None or code_minus is None:
            return Sample(
                sensor_name=raw_sample.sensor_name,
                sensor_kind="thrust",
                t_monotonic=raw_sample.t_monotonic,
                t_wall=raw_sample.t_wall,
                raw_value=raw_sample.raw_count,
                value=0.0,
                units="N",
                status="ERROR",
                message="missing raw_diff_1/raw_diff_2",
                source="simulated",
            )

        v_plus = self.adc_code_to_voltage(int(code_plus))
        v_minus = self.adc_code_to_voltage(int(code_minus))
        vdiff = abs(v_plus - v_minus)
        force_n = (vdiff / self.v_diff_fs) * self.max_load_n if self.v_diff_fs else 0.0

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="thrust",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=raw_sample.raw_count,
            value=force_n,
            units="N",
            V_diff_1=v_plus,
            V_diff_2=v_minus,
            source="simulated",
        )


class SimulatedRTDSensor(Sensor):
    def __init__(
        self,
        name: str,
        *,
        offset_c: float = 20.0,
        amplitude_c: float = 5.0,
        frequency_hz: float = 0.05,
        step_at_s: float = 5.0,
        step_c: float = 0.0,
        r0_ohms: float = 1000.0,
        alpha: float = 0.00385,
        idac_current_ua: float = 50.0,
        vref_internal: float = 2.5,
        noise_std_c: float = 0.1,
        seed: int = 2,
        channel: int = 0,
        unit: str = "°C",
    ):
        self.name = str(name)
        self.channel = int(channel)
        self.unit = unit

        self.offset_c = float(offset_c)
        self.amplitude_c = float(amplitude_c)
        self.frequency_hz = float(frequency_hz)
        self.step_at_s = float(step_at_s)
        self.step_c = float(step_c)
        self.noise_std_c = float(noise_std_c)
        self._rng = random.Random(int(seed))

        self.r0_ohms = float(r0_ohms)
        self.alpha = float(alpha)
        self.idac_current_ua = float(idac_current_ua)
        self.vref_internal = float(vref_internal)

        self._t0 = time.perf_counter()

    def _t(self, t_mono: float) -> float:
        return t_mono - self._t0

    def temperature_profile_c(self, t_s: float) -> float:
        t_c = self.offset_c + self.amplitude_c * math.sin(2.0 * math.pi * self.frequency_hz * t_s)
        if t_s > self.step_at_s:
            t_c += self.step_c
        if self.noise_std_c:
            t_c += self._rng.gauss(0.0, self.noise_std_c)
        return t_c

    def temp_c_to_resistance(self, temp_c: float) -> float:
        return self.r0_ohms * (1.0 + self.alpha * temp_c)

    def resistance_to_temp_c(self, resistance_ohm: float) -> float:
        if self.r0_ohms <= 0 or self.alpha == 0:
            return 0.0
        return (resistance_ohm / self.r0_ohms - 1.0) / self.alpha

    def _v_to_code(self, voltage_v: float) -> int:
        fs_code = (1 << 23) - 1
        voltage_v = max(-self.vref_internal, min(self.vref_internal, voltage_v))
        code = int(round((voltage_v / self.vref_internal) * fs_code))
        return max(-(1 << 23), min((1 << 23) - 1, code))

    def _code_to_v(self, code: int) -> float:
        fs_code = (1 << 23) - 1
        return (float(code) / fs_code) * self.vref_internal

    def _convert_unit(self, temp_c: float) -> float:
        if self.unit == "°F":
            return temp_c * 9.0 / 5.0 + 32.0
        if self.unit == "K":
            return temp_c + 273.15
        return temp_c

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        temp_c = self.temperature_profile_c(self._t(t_mono))
        res_ohm = self.temp_c_to_resistance(temp_c)
        i_idac = self.idac_current_ua * 1e-6
        v_rtd = res_ohm * i_idac
        code = self._v_to_code(v_rtd)

        # Provide single-ended "lead" codes for debugging parity with the real RTD sensor.
        code_lead1 = self._v_to_code(v_rtd / 2.0)
        code_lead2 = self._v_to_code(-v_rtd / 2.0)

        return RawSample(
            sensor_name=self.name,
            sensor_kind="temperature",
            conversion_type="sim_rtd",
            channel=self.channel,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=code,
            raw_diff_1=code_lead1,
            raw_diff_2=code_lead2,
        )

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code = int(raw_sample.raw_count)
        v_rtd = self._code_to_v(code)
        i_idac = self.idac_current_ua * 1e-6
        res_ohm = (v_rtd / i_idac) if i_idac else 0.0
        temp_c = self.resistance_to_temp_c(res_ohm)
        temp_disp = self._convert_unit(temp_c)

        v_diff_1 = self._code_to_v(int(raw_sample.raw_diff_1)) if raw_sample.raw_diff_1 is not None else None
        v_diff_2 = self._code_to_v(int(raw_sample.raw_diff_2)) if raw_sample.raw_diff_2 is not None else None

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="temperature",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=code,
            value=float(temp_disp),
            units=self.unit,
            V_diff_1=v_diff_1,
            V_diff_2=v_diff_2,
            source="simulated",
        )


# ------------------------- Hardware-backed sensors -------------------------


class LoadCellSensor(Sensor):
    """Hardware load cell sensor (ADS124S08 differential measurement)."""

    def __init__(
        self,
        name: str,
        *,
        adc: Any,
        sig_plus_ain: int,
        sig_minus_ain: int,
        max_load_n: float,
        excitation_voltage: float = 5.0,
        sensitivity_v_per_v: float = 0.0020,
        offset_n: float = 0.0,
        adc_vref: float = 5.0,
        adc_gain: float = 1.0,
    ):
        self.name = str(name)
        self.adc = adc
        self.sig_plus_ain = int(sig_plus_ain)
        self.sig_minus_ain = int(sig_minus_ain)
        self.max_load_n = float(max_load_n)
        self.excitation_voltage = float(excitation_voltage)
        self.sensitivity_v_per_v = float(sensitivity_v_per_v)
        self.offset_n = float(offset_n)
        self.adc_vref = float(adc_vref)
        self.adc_gain = float(adc_gain)

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        settle_discard = getattr(config, "ADC_SETTLE_DISCARD", True)
        sig_plus_raw = self.adc.read_raw_single(self.sig_plus_ain, settle_discard=settle_discard)
        sig_minus_raw = self.adc.read_raw_single(self.sig_minus_ain, settle_discard=settle_discard)
        raw_diff = self.adc.read_raw_diff(self.sig_plus_ain, self.sig_minus_ain, settle_discard=settle_discard)

        return RawSample(
            sensor_name=self.name,
            sensor_kind="load_cell",
            conversion_type="loadcell",
            channel=self.sig_plus_ain,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=int(raw_diff),
            raw_diff_1=int(sig_plus_raw),
            raw_diff_2=int(sig_minus_raw),
        )

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code_plus = raw_sample.raw_diff_1
        code_minus = raw_sample.raw_diff_2
        v_plus = _adc_code_to_voltage(int(code_plus), vref=self.adc_vref, gain=self.adc_gain) if code_plus is not None else 0.0
        v_minus = _adc_code_to_voltage(int(code_minus), vref=self.adc_vref, gain=self.adc_gain) if code_minus is not None else 0.0
        v_diff = abs(v_plus - v_minus)

        if self.excitation_voltage == 0 or self.sensitivity_v_per_v == 0:
            force_n = 0.0
        else:
            current_v_per_v = v_diff / self.excitation_voltage
            ratio = current_v_per_v / self.sensitivity_v_per_v
            force_n = ratio * self.max_load_n - self.offset_n

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="thrust",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=raw_sample.raw_count,
            value=float(force_n),
            units="N",
            V_diff_1=v_plus,
            V_diff_2=v_minus,
            source="hardware",
        )


class PressureTransducerSensor(Sensor):
    def __init__(
        self,
        name: str,
        *,
        adc: Any,
        sig_ain: int,
        v_min: float = 0.5,
        v_max: float = 4.5,
        p_min: float = 0.0,
        p_max: float = 1000.0,
        offset_psi: float = 0.0,
        adc_vref: float = 5.0,
        adc_gain: float = 1.0,
    ):
        self.name = str(name)
        self.adc = adc
        self.sig_ain = int(sig_ain)
        self.v_min = float(v_min)
        self.v_max = float(v_max)
        self.v_span = self.v_max - self.v_min
        self.p_min = float(p_min)
        self.p_max = float(p_max)
        self.p_span = self.p_max - self.p_min
        self.offset_psi = float(offset_psi)
        self.adc_vref = float(adc_vref)
        self.adc_gain = float(adc_gain)

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()
        settle_discard = getattr(config, "ADC_SETTLE_DISCARD", True)
        raw_code = self.adc.read_raw_single(self.sig_ain, settle_discard=settle_discard)
        return RawSample(
            sensor_name=self.name,
            sensor_kind="pressure",
            conversion_type="pt",
            channel=self.sig_ain,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=int(raw_code),
        )

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code = int(raw_sample.raw_count)
        voltage = _adc_code_to_voltage(code, vref=self.adc_vref, gain=self.adc_gain)
        if self.v_span == 0:
            pressure = self.p_min
        else:
            frac = (voltage - self.v_min) / self.v_span
            pressure = self.p_min + frac * self.p_span
        pressure -= self.offset_psi
        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="pressure",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=code,
            value=float(pressure),
            units="psi",
            V_diff_1=voltage,
            source="hardware",
        )


class RTDSensor(Sensor):
    """Hardware RTD sensor using ADC RTD mode (IDAC + internal ref)."""

    _VREF_INTERNAL = 2.5
    _FS = (1 << 23) - 1

    _CVD_A = 3.9083e-3
    _CVD_B = -5.775e-7
    _CVD_C = -4.183e-12

    def __init__(
        self,
        name: str,
        *,
        adc: Any,
        lead1_ain: int,
        lead2_ain: int,
        idac1_ain: int,
        idac2_ain: int,
        r0_ohms: float = 1000.0,
        idac_current_ua: float = 50.0,
        unit: str = "°C",
        offset: float = 0.0,
    ):
        self.name = str(name)
        self.adc = adc
        self.lead1_ain = int(lead1_ain)
        self.lead2_ain = int(lead2_ain)
        self.r0_ohms = float(r0_ohms)
        self.idac_current_ua = float(idac_current_ua)
        self.idac1_ain = int(idac1_ain)
        self.idac2_ain = int(idac2_ain)
        self.unit = unit
        self.offset = float(offset)

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        self.adc.enable_rtd_mode(
            current_ua=self.idac_current_ua,
            idac1_ain=self.idac1_ain,
            idac2_ain=self.idac2_ain,
        )

        try:
            settle_discard = getattr(config, "ADC_SETTLE_DISCARD", True)
            raw_lead1 = self.adc.read_raw_single(self.lead1_ain, settle_discard=settle_discard)
            raw_lead2 = self.adc.read_raw_single(self.lead2_ain, settle_discard=settle_discard)
            code_rtd = self.adc.read_raw_diff(self.lead1_ain, self.lead2_ain, settle_discard=settle_discard)
        finally:
            self.adc.disable_rtd_mode()

        return RawSample(
            sensor_name=self.name,
            sensor_kind="temperature",
            conversion_type="rtd",
            channel=self.lead1_ain,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=int(code_rtd),
            raw_diff_1=int(raw_lead1),
            raw_diff_2=int(raw_lead2),
        )

    def _code_to_resistance(self, code_rtd: int) -> float:
        v_rtd = (float(code_rtd) / self._FS) * self._VREF_INTERNAL
        i_idac = self.idac_current_ua * 1e-6
        return (v_rtd / i_idac) if i_idac else 0.0

    def _resistance_to_temperature_c(self, resistance: float) -> float:
        r_ratio = resistance / self.r0_ohms if self.r0_ohms else 0.0
        disc = self._CVD_A**2 - 4 * self._CVD_B * (1 - r_ratio)
        if disc < 0:
            return 0.0
        t_c = (-self._CVD_A + math.sqrt(disc)) / (2 * self._CVD_B)
        if t_c < 0:
            t_c = self._newton_cvd_negative(resistance, t_c)
        return t_c

    def _newton_cvd_negative(self, resistance: float, initial_guess: float, iterations: int = 10) -> float:
        A, B, C, R0 = self._CVD_A, self._CVD_B, self._CVD_C, self.r0_ohms
        t = float(initial_guess)
        for _ in range(iterations):
            r_calc = R0 * (1 + A * t + B * t**2 + C * (t - 100) * t**3)
            dr_dt = R0 * (A + 2 * B * t + C * (4 * t**3 - 300 * t**2))
            if abs(dr_dt) < 1e-15:
                break
            t -= (r_calc - resistance) / dr_dt
        return t

    def _convert_unit(self, temp_c: float) -> float:
        if self.unit == "°F":
            return temp_c * 9.0 / 5.0 + 32.0
        if self.unit == "K":
            return temp_c + 273.15
        return temp_c

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        resistance = self._code_to_resistance(int(raw_sample.raw_count))
        temp_c = self._resistance_to_temperature_c(resistance)
        temperature = self._convert_unit(temp_c) - self.offset
        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="temperature",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=raw_sample.raw_count,
            value=float(temperature),
            units=self.unit,
            source="hardware",
        )


class FlowMeterSensor(Sensor):
    """Placeholder base for a future flow meter implementation."""

    def __init__(self, name: str, **kwargs: Any):
        self.name = str(name)
        self.kwargs = dict(kwargs)

    def read_raw_sample(self) -> RawSample:
        raise NotImplementedError("FlowMeterSensor is not implemented yet")

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        raise NotImplementedError("FlowMeterSensor is not implemented yet")


def build_sensors(*, simulation: bool = True) -> list[Sensor]:
    """Create and return the list of sensor objects.

    - simulation=True: returns simulated sensors (runs without hardware).
    - simulation=False: hardware mode is not wired in the GUI runner yet.
    """
    if not simulation:
        if not sys.platform.startswith("linux"):
            raise NotImplementedError(
                "ADC mode requires Linux (Raspberry Pi) because it depends on SPI + libgpiod. "
                "Run with Simulation Mode ON when developing on Windows."
            )

        try:
            import yaml  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "PyYAML is required for ADC mode (hardware.yml / conversions.yml parsing). "
                "Install `pyyaml` in this environment."
            ) from e

        from deep_thrott_code.daq.drivers.adc import ADS124S08  # noqa: PLC0415

        def _load_yaml(path: Path) -> dict[str, Any]:
            if not path.exists():
                return {}
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}

        pkg_root = Path(__file__).resolve().parents[2]
        hardware_path = pkg_root / "config" / "hardware.yml"
        conversions_path = pkg_root / "config" / "conversions.yml"

        hardware_cfg = _load_yaml(hardware_path)
        conversions_cfg = _load_yaml(conversions_path)

        adcs_cfg = hardware_cfg.get("adcs")
        if not isinstance(adcs_cfg, dict) or not adcs_cfg:
            raise RuntimeError(f"No 'adcs' configured in {hardware_path}")

        adc_by_id: dict[str, Any] = {}
        for adc_id, cfg in adcs_cfg.items():
            if not isinstance(adc_id, str) or not isinstance(cfg, dict):
                continue

            if str(cfg.get("transport", "")).lower() != "spi":
                continue
            if str(cfg.get("model", "")).upper() not in {"ADS124S08IRHBT", "ADS124S08"}:
                continue

            spi_bus = cfg.get("spi_bus")
            spi_dev = cfg.get("spi_device")
            if spi_bus is None or spi_dev is None:
                continue

            cs_gpio = cfg.get("cs_gpio")
            reset_gpio = cfg.get("reset_gpio")
            drdy_gpio = cfg.get("drdy_gpio")

            cs_pin = int(cs_gpio) if cs_gpio is not None else None
            # Convention:
            # - cs_gpio set  -> use GPIO-controlled chip select (for "extra" CS lines)
            # - cs_gpio null -> use hardware CE line selected by spi_device

            adc = ADS124S08(
                id=adc_id,
                spi_bus=int(spi_bus),
                spi_dev=int(spi_dev),
                cs_pin=cs_pin,
                reset_pin=int(reset_gpio) if reset_gpio is not None else None,
                drdy_pin=int(drdy_gpio) if drdy_gpio is not None else None,
            )
            try:
                adc.hardware_reset()
                adc.configure_basic(use_internal_ref=False, gain=1)
                adc.start()
            except Exception:
                pass

            adc_by_id[adc_id] = adc

        sensors_cfg = hardware_cfg.get("sensors")
        pt_cfg = sensors_cfg.get("pressure_transducers") if isinstance(sensors_cfg, dict) else None
        rtd_cfg = (
            (sensors_cfg.get("rtds") or sensors_cfg.get("resistive temperature detectors"))
            if isinstance(sensors_cfg, dict)
            else None
        )
        lc_cfg = sensors_cfg.get("load_cells") if isinstance(sensors_cfg, dict) else None

        if not isinstance(pt_cfg, dict) or not pt_cfg:
            raise RuntimeError(f"No pressure transducers configured in {hardware_path}")

        def _pt_calibration(sensor_id: str) -> tuple[float, float, float, float]:
            default = (0.5, 4.5, 0.0, 1000.0)
            cal = conversions_cfg.get("calibration")
            if not isinstance(cal, dict):
                return default
            cal_pts = cal.get("pressure_transducers")
            if not isinstance(cal_pts, dict):
                return default
            entry = cal_pts.get(sensor_id)
            if not isinstance(entry, dict):
                return default
            profile_id = entry.get("profile")
            if not isinstance(profile_id, str) or not profile_id:
                return default

            profiles = conversions_cfg.get("calibration_profiles")
            if not isinstance(profiles, dict):
                return default
            pt_profiles = profiles.get("pressure_transducers")
            if not isinstance(pt_profiles, dict):
                return default
            profile = pt_profiles.get(profile_id)
            if not isinstance(profile, dict):
                return default
            if str(profile.get("type", "")).lower() != "volts_to_psi":
                return default

            try:
                v_min = float(profile.get("v_min", default[0]))
                v_max = float(profile.get("v_max", default[1]))
                psi_min = float(profile.get("psi_min", default[2]))
                psi_max = float(profile.get("psi_max", default[3]))
                return (v_min, v_max, psi_min, psi_max)
            except Exception:
                return default

        alias_by_sensor_id = {
            # Keep these names matching the GUI defaults/bindings.
            "CC-PT": "chamber_pressure",
            "FI-PT": "injector_pressure",
        }

        sensors: list[Sensor] = []
        for sensor_id, cfg in pt_cfg.items():
            if not isinstance(sensor_id, str) or not isinstance(cfg, dict):
                continue
            if not bool(cfg.get("enabled", False)):
                continue

            adc_id = cfg.get("adc_id")
            if not isinstance(adc_id, str) or adc_id not in adc_by_id:
                raise RuntimeError(f"Pressure transducer {sensor_id} references unknown adc_id={adc_id}")
            ain = cfg.get("ain")
            if ain is None:
                raise RuntimeError(f"Pressure transducer {sensor_id} is enabled but has no 'ain' set")

            v_min, v_max, p_min, p_max = _pt_calibration(sensor_id)
            name = alias_by_sensor_id.get(sensor_id, sensor_id)

            sensors.append(
                PressureTransducerSensor(
                    name=name,
                    adc=adc_by_id[adc_id],
                    sig_ain=int(ain),
                    v_min=v_min,
                    v_max=v_max,
                    p_min=p_min,
                    p_max=p_max,
                )
            )

        # rtd_cfg = rtd_cfg if isinstance(rtd_cfg, dict) else {}
        # for sensor_id, cfg in rtd_cfg.items():
        #     if not isinstance(sensor_id, str) or not isinstance(cfg, dict):
        #         continue
        #     if not bool(cfg.get("enabled", False)):
        #         continue

        #     adc_id = cfg.get("adc_id")
        #     if not isinstance(adc_id, str) or adc_id not in adc_by_id:
        #         raise RuntimeError(f"RTD {sensor_id} references unknown adc_id={adc_id}")
        #     lead1_ain = cfg.get("lead1_ain")
        #     lead2_ain = cfg.get("lead2_ain")
        #     idac1_ain = cfg.get("idac1_ain")
        #     idac2_ain = cfg.get("idac2_ain")
        #     if None in (lead1_ain, lead2_ain, idac1_ain, idac2_ain):
        #         raise RuntimeError(f"RTD {sensor_id} is enabled but missing one of lead1_ain/lead2_ain/idac1_ain/idac2_ain")

        #     sensors.append(
        #         RTDSensor(
        #             name=sensor_id,
        #             adc=adc_by_id[adc_id],
        #             lead1_ain=int(lead1_ain),
        #             lead2_ain=int(lead2_ain),
        #             idac1_ain=int(idac1_ain),
        #             idac2_ain=int(idac2_ain),
        #         )
        #     )

        # lc_cfg = lc_cfg if isinstance(lc_cfg, dict) else {}
        # for sensor_id, cfg in lc_cfg.items():
        #     if not isinstance(sensor_id, str) or not isinstance(cfg, dict):
        #         continue
        #     if not bool(cfg.get("enabled", False)):
        #         continue

        #     adc_id = cfg.get("adc_id")
        #     if not isinstance(adc_id, str) or adc_id not in adc_by_id:
        #         raise RuntimeError(f"Load cell {sensor_id} references unknown adc_id={adc_id}")
        #     sig_plus_ain = cfg.get("ain_pos")
        #     sig_minus_ain = cfg.get("ain_neg")
        #     if sig_plus_ain is None or sig_minus_ain is None:
        #         raise RuntimeError(f"Load cell {sensor_id} is enabled but missing ain_pos/ain_neg configuration")

        #     sensors.append(
        #         LoadCellSensor(
        #             name=sensor_id,
        #             adc=adc_by_id[adc_id],
        #             sig_plus_ain=int(sig_plus_ain),
        #             sig_minus_ain=int(sig_minus_ain),
        #             max_load_n=float(cfg.get("max_load", 1000.0)),
        #             excitation_voltage=float(cfg.get("excitation_voltage", 5.0)),
        #             sensitivity_v_per_v=float(cfg.get("sensitivity", 0.0020)),
        #             offset_n=float(cfg.get("offset", 0.0)),
        #         )
        #     )

        if not sensors:
            raise RuntimeError(
                "No enabled hardware sensors were built. Check 'enabled: true' and set AINs in hardware.yml."
            )

        return sensors

    return [
        SimulatedPressureSensor(
            name="chamber_pressure",
            offset=200.0,
            amplitude=20.0,
            frequency_hz=0.2,
            seed=0,
        ),
        SimulatedPressureSensor(
            name="injector_pressure",
            offset=300.0,
            amplitude=10.0,
            frequency_hz=0.1,
            seed=1,
        ),
        SimulatedLoadCellSensor(
            name="thrust",
            max_load_n=1000.0,
            amplitude_n=200.0,
            frequency_hz=0.5,
            seed=2,
        ),
        SimulatedRTDSensor(
            name="tank_temp",
            offset_c=20.0,
            amplitude_c=2.0,
            frequency_hz=0.02,
            seed=3,
        ),
    ]


def build_sensor_map(sensors: list[Sensor]) -> dict[str, Sensor]:
    """Build a mapping from sensor_name to sensor instance for the consumer loop."""
    return {sensor.name: sensor for sensor in sensors}


def _adc_for_cfg(cfg: dict[str, Any], adc1: Any, adc2: Any) -> Any:
    """Return the ADC instance (adc1 or adc2) for the given config's ADC index."""
    if cfg.get("ADC") == 1:
        return adc1
    if cfg.get("ADC") == 2:
        return adc2
    raise ValueError(f"Invalid ADC configuration: {cfg.get('ADC')}")
