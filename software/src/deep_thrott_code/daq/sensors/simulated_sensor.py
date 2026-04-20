from __future__ import annotations

import math
import random
import time

from ..services.sample import RawSample, Sample

class SimulatedPressureSensor:
    def __init__(
        self,
        name: str,
        offset: float,
        *,
        amplitude: float = 10.0,
        frequency_hz: float = 0.2,
        step_at_s: float = 5.0,
        step_psi: float = 50.0,
        p_min: float = 0.0,
        p_max: float = 500.0,
        v_min: float = 0.5,
        v_max: float = 4.5,
        adc_vref: float = 5.0,
        adc_gain: float = 1.0,
        noise_std: float = 1.0,
        seed: int = 0,
        channel: int = 0,
    ):
        self.name = name
        self.channel = int(channel)

        # "True" pressure signal parameters
        self.offset = float(offset)
        self.amplitude = float(amplitude)
        self.frequency_hz = float(frequency_hz)
        self.step_at_s = float(step_at_s)
        self.step_psi = float(step_psi)
        self.noise_std = float(noise_std)
        self._rng = random.Random(int(seed))

        # PT calibration
        self.p_min = float(p_min)
        self.p_max = float(p_max)
        self.v_min = float(v_min)
        self.v_max = float(v_max)

        # ADC model
        self.adc_vref = float(adc_vref)
        self.adc_gain = float(adc_gain)

        self._t0 = time.perf_counter()

    def _t(self, t_mono: float) -> float:
        return t_mono - self._t0

    def pressure_profile(self, t_s: float) -> float:
        p = self.offset + self.amplitude * math.sin(2.0 * math.pi * self.frequency_hz * t_s)
        if t_s > self.step_at_s:
            p += self.step_psi
        if self.noise_std:
            p += self._rng.gauss(0.0, self.noise_std)
        return p

    def pressure_to_voltage(self, pressure_psi: float) -> float:
        pressure_psi = max(self.p_min, min(self.p_max, pressure_psi))
        frac = (pressure_psi - self.p_min) / (self.p_max - self.p_min)
        return self.v_min + frac * (self.v_max - self.v_min)

    def voltage_to_pressure(self, voltage_v: float) -> float:
        voltage_v = max(self.v_min, min(self.v_max, voltage_v))
        frac = (voltage_v - self.v_min) / (self.v_max - self.v_min)
        return self.p_min + frac * (self.p_max - self.p_min)

    def voltage_to_adc_code(self, voltage_v: float) -> int:
        full_scale = self.adc_vref / self.adc_gain
        voltage_v = max(-full_scale, min(full_scale, voltage_v))

        fs_code = (1 << 23) - 1
        code = int(round((voltage_v / full_scale) * fs_code))
        return max(-(1 << 23), min((1 << 23) - 1, code))

    def adc_code_to_voltage(self, code: int) -> float:
        fs_code = (1 << 23) - 1
        full_scale = self.adc_vref / self.adc_gain
        return (float(code) / fs_code) * full_scale

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
        v = self.adc_code_to_voltage(code)
        p = self.voltage_to_pressure(v)

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="pressure",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=code,
            value=p,
            units="psi",
            source="simulated",
        )


class SimulatedLoadCellSensor:
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
        self.name = name
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

    def force_profile(self, t_s: float) -> float:
        f = self.offset_n + self.amplitude_n * math.sin(2.0 * math.pi * self.frequency_hz * t_s)
        if t_s > self.step_at_s:
            f += self.step_n
        if self.noise_std_n:
            f += self._rng.gauss(0.0, self.noise_std_n)
        return f

    def voltage_to_adc_code(self, voltage_v: float) -> int:
        full_scale = self.adc_vref / self.adc_gain
        voltage_v = max(-full_scale, min(full_scale, voltage_v))

        fs_code = (1 << 23) - 1
        code = int(round((voltage_v / full_scale) * fs_code))
        return max(-(1 << 23), min((1 << 23) - 1, code))

    def adc_code_to_voltage(self, code: int) -> float:
        fs_code = (1 << 23) - 1
        full_scale = self.adc_vref / self.adc_gain
        return (float(code) / fs_code) * full_scale

    def _force_to_vdiff(self, force_n: float) -> float:
        if self.max_load_n <= 0:
            return 0.0
        ratio = max(-1.0, min(1.0, force_n / self.max_load_n))
        return ratio * self.v_diff_fs

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        force_n = self.force_profile(self._t(t_mono))
        vdiff = self._force_to_vdiff(force_n)

        v_plus = self.v_common + 0.5 * vdiff
        v_minus = self.v_common - 0.5 * vdiff

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


class SimulatedRTDSensor:
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
        self.name = name
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

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        temp_c = self.temperature_profile_c(self._t(t_mono))
        r = self.temp_c_to_resistance(temp_c)

        i = self.idac_current_ua * 1e-6
        v = r * i if i else 0.0
        code = self._v_to_code(v)

        return RawSample(
            sensor_name=self.name,
            sensor_kind="temperature",
            conversion_type="sim_rtd",
            channel=self.channel,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=code,
        )

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code = int(raw_sample.raw_count)
        v = self._code_to_v(code)

        i = self.idac_current_ua * 1e-6
        r = (v / i) if i else 0.0
        temp_c = self.resistance_to_temp_c(r)

        value = temp_c
        units = "°C"
        if self.unit == "°F":
            value = temp_c * 9.0 / 5.0 + 32.0
            units = "°F"
        elif self.unit == "K":
            value = temp_c + 273.15
            units = "K"

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="temperature",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=code,
            value=value,
            units=units,
            source="simulated",
        )

