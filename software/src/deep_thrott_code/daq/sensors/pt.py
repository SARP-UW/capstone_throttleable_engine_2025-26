"""
Sensor classes for converting analog voltage readings to physical values.
"""

import math
from .. import config
import time
from ..services.sample import RawSample, Sample

# TODO: edit owen's sensor classes to not to voltage and pressure conversion in the same method, 
# split them up for producer and consumer loop 

class PressureTransducer:
    """
    Pressure transducer sensor that reads voltage from a single analog input.

    Args:
        sig_idx (int): Voltage list index for signal input
        excitation_voltage (float): Excitation voltage (default: 5.0)
        V_max (float): Maximum voltage (default: 4.5)
        V_min (float): Minimum voltage (default: 0.5)
        V_span (float): Voltage span (default: 4.0)
        P_min (float): Minimum pressure (default: 0.0)
        P_max (float): Maximum pressure (default: 100.0)
    """

    def __init__(self, ADC, sig_idx, excitation_voltage=5.0, V_max=4.5, V_min=0.5, V_span=4.0, P_min=0.0, P_max=100.0, offset=0.0):
        self.ADC = ADC
        self.sig_idx = sig_idx
        self.excitation_voltage = excitation_voltage
        self.V_max = V_max
        self.V_min = V_min
        self.V_span = V_span
        self.P_min = P_min
        self.P_max = P_max
        self.offset = float(offset)

        # Add other attributes such as calibration and correct channel numbers
    
    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        raw_code = self.ADC.read_raw_single()

        return RawSample(
            sensor_name=self.name,
            sensor_kind="pressure",
            conversion_type="pt",
            channel=self.sig_idx,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=raw_code,
        )
    
    def code_to_voltage(self, code: int):
        fs_code = (1 << 23) - 1
        voltage = (code / fs_code) * (self.adc_vref / self.adc_gain)
        return voltage

    def convert_voltage_to_pressure(self, voltage: float):
        frac = (voltage - self.V_min) / self.V_span
        pressure = self.P_min + frac * (self.P_max - self.P_min)
        return pressure

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        code = raw_sample.raw_count

        voltage = self.code_to_voltage(code)
        pressure = self.convert_voltage_to_pressure(voltage)

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="pressure",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=code,
            value=pressure,
            units="psi",
            source="simulated"
        )
