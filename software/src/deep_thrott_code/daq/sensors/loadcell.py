"""
Sensor classes for converting analog voltage readings to physical values.
"""

import math
import software.src.deep_thrott_code.daq.config as config
from software.src.deep_thrott_code.daq.services.sample import RawSample, Sample
import time

class Load_Cell:
    """
    Load cell sensor that reads differential voltage from two analog inputs.

    Args:
        sig_plus_idx (int): Voltage list index for positive signal
        sig_minus_idx (int): Voltage list index for negative signal
        excitation_voltage (float): Excitation voltage (default: 5.0)
        sensitivity (float): Sensitivity in mV/V (default: 0.020)
    """

    def __init__(self, ADC, sig_plus_idx, sig_minus_idx, max_load, excitation_voltage=5.0, sensitivity=0.0020, offset=0.0):
        self.ADC = ADC
        self.sig_plus_idx = sig_plus_idx
        self.sig_minus_idx = sig_minus_idx
        self.excitation_voltage = excitation_voltage
        self.sensitivity = sensitivity
        self.max_load = max_load
        self.offset = float(offset)
    
    def code_to_voltage(self, code: int):
        fs_code = (1 << 23) - 1
        voltage = (code / fs_code) * (self.adc_vref / self.adc_gain)
        return voltage
    
    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        sig_plus_raw = self.ADC.read_raw_single(self.sig_plus_idx, 
                                                settle_discard=config.ADC_SETTLE_DISCARD)
        sig_minus_raw = self.ADC.read_raw_single(self.sig_minus_idx, 
                                                 settle_discard=config.ADC_SETTLE_DISCARD)
        raw_signal = self.ADC.read_raw_diff(self.sig_plus_idx, self.sig_minus_idx, 
                                            settle_discard=config.ADC_SETTLE_DISCARD)

        return RawSample(
            sensor_name=self.name,
            sensor_kind="load_cell",
            channel=self.sig_idx,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=raw_signal,
            raw_diff_1=sig_plus_raw,
            raw_diff_2=sig_minus_raw
        )

    def _calculate_force(self, sig_plus, sig_minus):
        """
        Calculate force from differential voltage.
        Placeholder implementation - to be completed later.

        Args:
            sig_plus (float): Positive signal voltage
            sig_minus (float): Negative signal voltage

        Returns:
            float: Calculated force
        """

        """
        Calculate normalized force ratio.
        """
        # 1. Calculate differential voltage (e.g. 0.008 V)
        v_diff = abs(sig_plus - sig_minus)

        # 2. Avoid division by zero errors
        if self.excitation_voltage == 0 or self.sensitivity == 0:
            return 0.0

        # 3. Calculate current mV/V reading
        # Example: 0.008V / 5.0V = 0.0016 V/V = 1.6 mV/V
        current_mv_per_v = v_diff / self.excitation_voltage

        # 4. Calculate ratio of Full Scale
        # Example: 1.6 mV/V / 2.0 mV/V (sensitivity) = 0.8 (80% load)
        ratio = current_mv_per_v / self.sensitivity

        return (ratio * self.max_load) - self.offset
    

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        
        force = self._calculate_force(
            sig_plus=self.ADC.code_to_voltage(raw_sample.raw_diff_1),
            sig_minus=self.ADC.code_to_voltage(raw_sample.raw_diff_2)
        )

        voltage_diff_1 = self.ADC.code_to_voltage(raw_sample.raw_diff_1)
        voltage_diff_2 = self.ADC.code_to_voltage(raw_sample.raw_diff_2)

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="thrust",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=raw_sample.raw_count,
            value=force,
            units="N",
            V_diff_1=voltage_diff_1,
            V_diff_2=voltage_diff_2
        )

