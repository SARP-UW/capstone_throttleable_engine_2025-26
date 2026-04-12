
from services.sample import RawSample, Sample
import time
import math
import random
import math

from sensors.rtd import RTD
from sensors.pt import PressureTransducer

# class SimulatedSensor:
#     def __init__(self, sensor, generator):
#         self.sensor = sensor
#         self.generator = generator

#     def read(self, t):
#         return self.generator(t)

# SENSOR_MAP = {
#     0: SimulatedSensor(
#         sensor=RTD(id=0, calibration=...),
#         generator=lambda t: 100 + 5 * math.sin(t)
#     ),
#     1: SimulatedSensor(
#         sensor=PressureTransducer(ADC=None, sig_idx=1, calibration=...),
#         generator=lambda t: 300 + 10 * math.sin(0.2 * t)
#     ),
# }


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

