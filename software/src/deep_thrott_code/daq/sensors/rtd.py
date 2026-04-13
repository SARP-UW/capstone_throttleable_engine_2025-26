"""
Sensor classes for converting analog voltage readings to physical values.
"""

import math
import software.src.deep_thrott_code.daq.config as config
from software.src.deep_thrott_code.daq.services.sample import RawSample, Sample
import time


class RTD:
    """
    3-wire RTD sensor using software-ratiometric measurement with IDAC excitation.

    Enables RTD mode (switches ADC to internal 2.5 V reference, turns on
    IDACs), reads both the RTD voltage (L1-L2) and the Rref voltage
    (REFP-REFN) differentially, then takes their ratio so that both IDAC
    current and internal reference voltage cancel.  Finally restores the
    ADC to its normal state so other sensors are unaffected.

    Temperature is computed via the Callendar-Van Dusen equation (IEC 60751).
    """

    # Callendar-Van Dusen coefficients (IEC 60751)
    _CVD_A = 3.9083e-3
    _CVD_B = -5.775e-7
    _CVD_C = -4.183e-12  # only used for T < 0 °C

    def __init__(self, ADC, V_lead1_idx, V_lead2_idx,
                 refp_ain=7, refn_ain=6,
                 r0=1000.0, rref=5600.0,
                 idac_current_ua=50, idac1_ain=5, idac2_ain=3,
                 unit="°C", offset=0.0):
        self.ADC = ADC
        self.V_lead1_idx = V_lead1_idx
        self.V_lead2_idx = V_lead2_idx
        self.refp_ain = refp_ain
        self.refn_ain = refn_ain
        self.r0 = float(r0)
        self.rref = float(rref)
        self.idac_current_ua = idac_current_ua
        self.idac1_ain = idac1_ain
        self.idac2_ain = idac2_ain
        self.unit = unit
        self.offset = float(offset)

    _VREF_INTERNAL = 2.5
    _FS = (1 << 23) - 1  # 8 388 607

    def read_raw_sample(self) -> RawSample:
        t_mono = time.perf_counter()
        t_wall = time.time()

        self.ADC.enable_rtd_mode(
            current_ua=self.idac_current_ua,
            idac1_ain=self.idac1_ain,
            idac2_ain=self.idac2_ain,
        )

        # edit this to be more lightweight, edit RawSample attributes if needed
        try:
            raw_lead1 = self.ADC.read_raw_single(self.V_lead1_idx, 
                                                 settle_discard=config.ADC_SETTLE_DISCARD)
            raw_lead2 = self.ADC.read_raw_single(self.V_lead2_idx, 
                                                 settle_discard=config.ADC_SETTLE_DISCARD)
            
            code_rtd = self.ADC.read_raw_diff(
                self.V_lead1_idx,
                self.V_lead2_idx,
                settle_discard=config.ADC_SETTLE_DISCARD,
            )

        finally:
            self.ADC.disable_rtd_mode()

        return RawSample(
            sensor_name=self.name,
            sensor_kind="temperature",
            conversion_type="rtd",
            channel=self.sig_idx,
            t_monotonic=t_mono,
            t_wall=t_wall,
            raw_count=code_rtd, 
            raw_diff_1=raw_lead1, 
            raw_diff_2=raw_lead2
        )

    def convert_raw_sample_to_sample(self, raw_sample: RawSample) -> Sample:
        """
        Enable RTD excitation, read L1 and L2 single-ended voltages plus
        the differential code across the RTD, disable RTD excitation, then
        compute resistance and temperature.

        Resistance is computed as R = V_RTD / I_IDAC.  The IDAC current only
        flows through the RTD (not through Rref), so a software-ratiometric
        approach using Rref would give the wrong answer for this circuit
        topology where the Rbias chain contributes extra current through Rref.

        Returns:
            (v_lead1, v_lead2, resistance, temperature)
        """

        resistance = self._code_to_resistance(raw_sample.raw_count)
        temp_c = self._resistance_to_temperature(resistance)
        temperature = self._convert_unit(temp_c) - self.offset

        v_diff_1 = self.code_to_voltage(raw_sample.raw_diff_1)
        v_diff_2 = self.code_to_voltage(raw_sample.raw_diff_2)

        return Sample(
            sensor_name=raw_sample.sensor_name,
            sensor_kind="temperature",
            t_monotonic=raw_sample.t_monotonic,
            t_wall=raw_sample.t_wall,
            raw_value=raw_sample.raw_count,
            value=temperature,
            units=self.unit,
            V_diff_1=v_diff_1,
            V_diff_2=v_diff_2
        )

    def code_to_voltage(self, code: int):
        fs_code = (1 << 23) - 1
        voltage = (code / fs_code) * (self.adc_vref / self.adc_gain)
        return voltage
    
    def _code_to_resistance(self, code_rtd):
        """R = V_RTD / I_IDAC, where V_RTD is derived from the raw ADC code."""
        v_rtd = (code_rtd / self._FS) * self._VREF_INTERNAL
        i_idac = self.idac_current_ua * 1e-6
        if i_idac == 0:
            return 0.0
        return v_rtd / i_idac

    def _resistance_to_temperature(self, resistance):
        """Invert the Callendar-Van Dusen equation to get temperature in °C."""
        r_ratio = resistance / self.r0

        # Quadratic inverse for T >= 0 °C:
        #   R/R0 = 1 + A*T + B*T^2  =>  B*T^2 + A*T + (1 - R/R0) = 0
        discriminant = self._CVD_A ** 2 - 4 * self._CVD_B * (1 - r_ratio)
        if discriminant < 0:
            return 0.0
        temp_c = (-self._CVD_A + math.sqrt(discriminant)) / (2 * self._CVD_B)

        if temp_c < 0:
            temp_c = self._newton_cvd_negative(resistance, temp_c)

        return temp_c

    def _newton_cvd_negative(self, resistance, initial_guess, iterations=10):
        """Newton-Raphson refinement for T < 0 °C (full CVD with C term)."""
        A, B, C, R0 = self._CVD_A, self._CVD_B, self._CVD_C, self.r0
        t = initial_guess
        for _ in range(iterations):
            r_calc = R0 * (1 + A * t + B * t**2 + C * (t - 100) * t**3)
            dr_dt = R0 * (A + 2 * B * t + C * (4 * t**3 - 300 * t**2))
            if abs(dr_dt) < 1e-15:
                break
            t -= (r_calc - resistance) / dr_dt
        return t

    def _convert_unit(self, temp_c):
        """Convert from °C to the configured display unit."""
        if self.unit == "°F":
            return temp_c * 9.0 / 5.0 + 32.0
        if self.unit == "K":
            return temp_c + 273.15
        return temp_c

