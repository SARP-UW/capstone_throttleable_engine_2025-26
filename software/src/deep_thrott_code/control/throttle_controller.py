from pid import PID
import threading
import # ../daq/services/state_store.py ??? 

# needed in the F3C file where this funct is called: stop_event = threading.Event()

def throttle_loop(chamber_PT: StateStore, stop_event, ):
    """
    chamber_pt: this is an instance of the StateStore class
    stop_event: this is an instance of the Event class in the threading library
    """
    
    # figure out how to implement: while not stop_event.is_set():

    # Define PID gains
    kp = 1
    ki = 0
    kd = 0

    # Define measurement frequency in seconds
    dt = 0.01

    # Initialize PID object
    MyPID = PID(kp, ki, kd)

    # Read current chamber pressure
    Pc_current = chamber_PT.get(sample)

    # Initialize previous chamber pressure
    Pc_previous = Pc_current

    while true

        if state = throttle
            
            # Read current chamber pressure
            Pc_current = store_state.get(sample)

            # Call PID_output function to create PID output
            PID_output = MyPID.PID_output(reference, Pc_current, Pc_previous, dt)


            # Send PID_output to F3C loop

            # Set Pc_previous to the Pc_current value that was already used
            Pc_previous = Pc_current

        