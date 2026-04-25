import queue
import threading
import time

from .services.loop import consumer_loop, producer_loop
from .services.logger import CsvLogger
from .services.state_store import StateStore
from .sensors.sensors import build_sensor_map, build_sensors
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
#       - status message for gui on initialization 
#       - make config file and also initialize sensor list


def main():
    sample_queue = queue.Queue(maxsize=1000)
    gui_queue = queue.Queue(maxsize=100)
    stop_event = threading.Event()
    state_store = StateStore()
    logger = CsvLogger("daq_log.csv")

    sensors = build_sensors()
    sensor_map = build_sensor_map(sensors)

    producer_thread = threading.Thread(
        target=producer_loop,
        args=(sensors, sample_queue, stop_event, 50.0),
        daemon=True,
        name="producer",
    )
    
    consumer_thread = threading.Thread(
        target=consumer_loop,
        args=(sample_queue, gui_queue, state_store, logger, stop_event, sensor_map),
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