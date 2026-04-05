"""
Sensor classes for converting analog voltage readings to physical values.
"""

import math
import software.src.deep_thrott_code.daq.config as config

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

    def read(self):
        sig_plus = self.ADC.read_voltage_single(self.sig_plus_idx, settle_discard=config.ADC_SETTLE_DISCARD)
        sig_minus = self.ADC.read_voltage_single(self.sig_minus_idx, settle_discard=config.ADC_SETTLE_DISCARD)

        # Placeholder calculation - to be implemented later
        return sig_plus, sig_minus, self._calculate_force(sig_plus, sig_minus)

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

