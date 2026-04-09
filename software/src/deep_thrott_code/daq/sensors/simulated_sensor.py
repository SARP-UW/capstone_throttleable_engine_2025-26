
from services.sample import RawSample, Sample
import time
import math
import random

class SimulatedPressureSensor:
    def __init__(
        self,
        name,
        offset,              # baseline pressure (psi)
        p_min=0.0,
        p_max=500.0,
        v_min=0.5,
        v_max=4.5,
        adc_vref=5.0,
        adc_gain=1,
        noise_std=1.0,       # pressure noise (psi)
    ):
        self.name = name
        self.offset = offset

        # PT calibration
        self.p_min = p_min
        self.p_max = p_max
        self.v_min = v_min
        self.v_max = v_max

        # ADC config
        self.adc_vref = adc_vref
        self.adc_gain = adc_gain

        self.noise_std = noise_std
        self.t0 = time.perf_counter()

    # -----------------------
    # True pressure model
    # -----------------------
    def pressure_profile(self, t):
        """
        Simulated pressure vs time.
        You can change this freely.
        """
        # baseline + slow oscillation + step
        p = self.offset + 10.0 * math.sin(2 * math.pi * 0.2 * t)

        if t > 5.0:
            p += 50.0

        p += random.gauss(0.0, self.noise_std)

        return p

    # -----------------------
    # PT model: pressure → voltage
    # -----------------------
    def pressure_to_voltage(self, pressure):
        pressure = max(self.p_min, min(self.p_max, pressure))

        frac = (pressure - self.p_min) / (self.p_max - self.p_min)
        voltage = self.v_min + frac * (self.v_max - self.v_min)

        return voltage

    # -----------------------
    # ADC model: voltage → count
    # -----------------------
    def voltage_to_adc_code(self, voltage):
        full_scale = self.adc_vref / self.adc_gain

        voltage = max(-full_scale, min(full_scale, voltage))

        fs_code = (1 << 23) - 1  # 24-bit signed ADC
        code = int(round((voltage / full_scale) * fs_code))

        code = max(-(1 << 23), min((1 << 23) - 1, code))
        return code

    # -----------------------
    # Producer: generate raw sample
    # -----------------------
    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()
        t = t_mono - self.t0

        # 1. true pressure
        pressure = self.pressure_profile(t)

        # 2. pressure → voltage
        voltage = self.pressure_to_voltage(pressure)

        # 3. voltage → ADC count
        raw_code = self.voltage_to_adc_code(voltage)

        return RawSample(
            sensor_name=self.name,
            sensor_kind="pressure",
            channel=0,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=raw_code,
            source="simulated"
        )

    # -----------------------
    # Consumer: convert raw → engineering units
    # -----------------------
    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code = raw_sample.raw_count

        # ADC count → voltage
        fs_code = (1 << 23) - 1
        voltage = (code / fs_code) * (self.adc_vref / self.adc_gain)

        # voltage → pressure
        frac = (voltage - self.v_min) / (self.v_max - self.v_min)
        pressure = self.p_min + frac * (self.p_max - self.p_min)

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="pressure",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=code,
            value=pressure,
            units="psi",
            status="ok",
            source="simulated"
        )