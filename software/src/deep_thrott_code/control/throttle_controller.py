from pid import PID
import time
import numpy as np

def throttle_loop(chamber_PT, stop_event, throttle_profile, state_store):
    """
    chamber_PT: StateStore for chamber pressure
    stop_event: threading.Event()
    throttle_profile: function or object that returns Pc_ref at current time
    state_store: interface to check if system state is "throttle"
    """

    # PID gains
    kp = 1
    ki = 0
    kd = 0

    dt = 0.01  # 100 Hz loop
    pid = PID(kp, ki, kd)

    # Feedforward lookup table
    Pc_bp = np.array([0, 5e5, 1e6, 1.5e6, 2e6])
    theta_ff_table = np.array([0, 10, 25, 40, 55])

    def feedforward_angle(Pc_ref):
        return float(np.interp(Pc_ref, Pc_bp, theta_ff_table))

    # Initial measurement
    # Need to import StateStore in file where throttle_loop function is called to use .get
    Pc_previous = chamber_PT.get("CC-PT")

    t0 = time.perf_counter()

    # Need to import threading in file where throttle_loop function is called to use .is_set
    while not stop_event.is_set():
        
        # How to implement getting state?
        if state_store.get_state() == "throttle":

            # 1. Get reference from throttle profile
            t = time.perf_counter() - t0
            Pc_ref = throttle_profile(t)

            # 2. Read chamber pressure
            Pc_current = chamber_PT.get("CC-PT")

            # 3. Feedforward valve angle
            theta_ff = feedforward_angle(Pc_ref)

            # 4. PID correction
            theta_pid = pid.PID_output(Pc_ref, Pc_current, Pc_previous, dt)

            # 5. Combine
            theta_cmd = theta_ff + theta_pid

            # 6. Clamp to physical valve limits
            theta_cmd = max(0, min(theta_cmd, 90))

            # 7. Send to F3C?
            state_store.send_throttle_command(theta_cmd)

            # 8. Update previous
            Pc_previous = Pc_current

        time.sleep(dt)
