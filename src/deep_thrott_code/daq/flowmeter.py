"""
Sensor classes for converting analog voltage readings to physical values.
"""

import math
import config


class Pressure_Transducer:
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

    def read(self):
        sig_voltage = self.ADC.read_voltage_single(self.sig_idx, settle_discard=config.ADC_SETTLE_DISCARD)

        # Placeholder calculation - to be implemented later
        return sig_voltage, self._calculate_pressure(sig_voltage)

    def _calculate_pressure(self, sig_voltage):
        """
        Calculate pressure from voltage reading.
        Placeholder implementation - to be completed later.

        Args:
            sig_voltage (float): Signal voltage

        Returns:
            float: Calculated pressure
        """

        # Linear mapping
        pressure = (sig_voltage - self.V_min) * ((self.P_max - self.P_min) / self.V_span) + self.P_min

        return pressure - self.offset

