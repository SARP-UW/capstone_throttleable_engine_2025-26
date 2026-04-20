"""
Sensor classes for converting analog voltage readings to physical values.
"""

# what are any of these used for?

from __future__ import annotations

import math
import time

from .. import config
from ..services.sample import RawSample, Sample
from .loadcell import Load_Cell
from .pt import PressureTransducer
from .rtd import RTD
from .simulated_sensor import SimulatedLoadCellSensor, SimulatedPressureSensor, SimulatedRTDSensor

# what is this?? is it supposed to be in ADC class? 
def _adc_for_cfg(cfg, adc1, adc2):
    """Return the ADC instance (adc1 or adc2) for the given config's ADC index."""
    if cfg["ADC"] == 1:
        return adc1
    if cfg["ADC"] == 2:
        return adc2
    raise ValueError(f"Invalid ADC configuration: {cfg['ADC']}")


def build_sensors():
    """
    Create and return the list of sensor objects.
    Start with simulated sensors, then replace with real ones.
    """
    sensors = [
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
    return sensors


def build_sensor_map(sensors):
    """
    Build a mapping from sensor_id to sensor instance for the consumer loop.
    This allows the consumer loop to call the correct conversion method based on the sensor type.
    """
    sensor_map = {}
    for sensor in sensors:
        sensor_map[sensor.name] = sensor
    return sensor_map


def initialize_sensors(adc1, adc2):
    sensor_labels = []
    load_cells = []
    for name, cfg in config.LOAD_CELLS.items():
        if cfg["enabled"]:
            print(f"Initializing Load Cell {name} with sig_plus_idx {cfg['SIG+']} and sig_minus_idx {cfg['SIG-']}")
            selected_adc = _adc_for_cfg(cfg, adc1, adc2)
            sensor = Load_Cell(
                ADC=selected_adc,
                sig_plus_idx=cfg["SIG+"],
                sig_minus_idx=cfg["SIG-"],
                max_load=cfg["max_load"],
                excitation_voltage=cfg["excitation_voltage"],
                sensitivity=cfg["sensitivity"],
                offset=float(cfg.get("offset", 0)),
            )
            load_cells.append((name, sensor))
            sensor_labels.append(name)

    pressure_transducers = []
    for name, cfg in config.PRESSURE_TRANSDUCERS.items():
        if cfg["enabled"]:
            print(f"Initializing Pressure Transducer {name} with sig_idx {cfg['SIG']}")
            selected_adc = _adc_for_cfg(cfg, adc1, adc2)
            sensor = PressureTransducer(
                ADC=selected_adc,
                sig_idx=cfg["SIG"],
                excitation_voltage=cfg["excitation_voltage"],
                V_max=cfg["V_max"],
                V_min=cfg["V_min"],
                V_span=cfg["V_span"],
                P_min=cfg["P_min"],
                P_max=cfg["P_max"],
                offset=float(cfg.get("offset", 0)),
            )
            pressure_transducers.append((name, sensor))
            sensor_labels.append(name)

    rtds = []
    for name, cfg in config.RTDS.items():
        if cfg["enabled"]:
            print(f"Initializing RTD {name} on ADC{cfg['ADC']} "
                  f"L1=AIN{cfg['L1']} L2=AIN{cfg['L2']} "
                  f"IDAC={cfg.get('idac_current_ua', 50)}µA "
                  f"R0={cfg.get('r0', 1000)}Ω Rref={cfg.get('rref', 5600)}Ω")
            selected_adc = _adc_for_cfg(cfg, adc1, adc2)
            sensor = RTD(
                ADC=selected_adc,
                V_lead1_idx=cfg["L1"],
                V_lead2_idx=cfg["L2"],
                refp_ain=cfg.get("refp_ain", 7),
                refn_ain=cfg.get("refn_ain", 6),
                r0=cfg.get("r0", 1000.0),
                rref=cfg.get("rref", 5600.0),
                idac_current_ua=cfg.get("idac_current_ua", 50),
                idac1_ain=cfg.get("idac1_ain", 5),
                idac2_ain=cfg.get("idac2_ain", 3),
                unit=cfg.get("unit", "°C"),
                offset=float(cfg.get("offset", 0)),
            )
            rtds.append((name, sensor))
            sensor_labels.append(name)

    return sensor_labels, load_cells, pressure_transducers, rtds

# what is this?
def read_sensors(load_cells, pressure_transducers, rtds):
    sensor_values = []
    csv_columns = []
    for _, sensor in load_cells:
        v_sig_plus, v_sig_minus, force = sensor.read()
        csv_columns.extend([v_sig_plus, v_sig_minus, force])
        sensor_values.append(force)
    for _, sensor in pressure_transducers:
        v_p_sig, pressure = sensor.read()
        csv_columns.extend([v_p_sig, pressure])
        sensor_values.append(pressure)
    for _, sensor in rtds:
        v_lead1, v_lead2, resistance, temperature = sensor.read()
        csv_columns.extend([v_lead1, v_lead2, temperature])
        sensor_values.append(temperature)
    return csv_columns, sensor_values