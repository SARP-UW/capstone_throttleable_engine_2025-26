import queue
import threading
import time

from services.loop import producer_loop
from services.loop import consumer_loop
from services.state_store import StateStore
from services.logger import CsvLogger

from sensors.simulated_sensor import SimulatedPressureSensor
# later:
# from drivers.ads124s08 import ADS124S08
# from sensors.pt import PressureSensor
# from sensors.rtd import RTD 
# from sensors.flowmeter import FlowMeter
# from sensors.loadcell import LoadCell

# i should do this: each physical sensor = one instance of the sensor class itself for easy reference 
# of mapping of adc pins (this is for the producer loop), every instance carries their own calibration 
# with them and there's an attribute on the RawSample class that carries the id for the instance. and 
# then using that id the consumer loop will know what method to call based on what sensor class that 
# RawSample belong to

# TODO: - add read_sample method for all sensor classes
#       - split up tasks in sensor classes so conversions aren't happening all in one method
#       - edit consumer loop and batch processing functions


def build_sensors():
    """
    Create and return the list of sensor objects.
    Start with simulated sensors, then replace with real ones.
    """
    sensors = [
        SimulatedPressureSensor(name="chamber_pressure", offset=200.0, amplitude=20.0, frequency_hz=0.2),
        SimulatedPressureSensor(name="injector_pressure", offset=300.0, amplitude=10.0, frequency_hz=0.1),
    ]
    return sensors


def main():
    sample_queue = queue.Queue(maxsize=1000)
    stop_event = threading.Event()
    state_store = StateStore()
    logger = CsvLogger("daq_log.csv")

    sensors = build_sensors()

    producer_thread = threading.Thread(
        target=producer_loop,
        args=(sensors, sample_queue, stop_event, 50.0),
        daemon=True,
        name="producer",
    )
    
    consumer_thread = threading.Thread(
        target=consumer_loop,
        args=(sample_queue, state_store, logger, stop_event),
        daemon=True,
        name="consumer",
    )

    threads = [producer_thread, consumer_thread]

    for thread in threads:
        thread.start()

    print("DAQ started. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1.0)

            snapshot = state_store.snapshot()
            if "chamber_pressure" in snapshot:
                pc = snapshot["chamber_pressure"]
                print(f"Pc = {pc.value:.2f} {pc.units} [{pc.status}]")

    except KeyboardInterrupt:
        print("\nStopping DAQ...")
        stop_event.set()

        for thread in threads:
            thread.join(timeout=2.0)

        logger.close()
        print("DAQ stopped cleanly.")


if __name__ == "__main__":
    main()