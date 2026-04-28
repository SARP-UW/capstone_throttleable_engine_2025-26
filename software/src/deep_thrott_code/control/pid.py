

class PID:
    """
    Basic PID class

    Args
        self: name of PID object
        kp: proportional gain
        ki: integral gain
        kd: derivative gain

    Returns
        PID_output: output of PID object, commanded value
        
    """

    def __init__(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral_error = 0

    def PID_output(self, reference, current_value, previous_value, dt):
        """        
        self: name of PID object
        reference: desired value of process variable
        current_value: current measured value of process variable
        previous_value: previous meausured value of process variable - value that was read a time interview of dt before current_value
        dt: time interval between measurements

        returns
            PID_output: output of PID object, commanded value

        """
        self.reference = reference
        self.current_value = current_value
        self.previous_value = previous_value
        self.dt = dt

        error = self.reference - self.current_value
        self.integral_error += self.integral_error + error * self.dt
        derivative_error = (self.current_value - self.previous_value)/self.dt
        PID_output = self.kp * error + self.ki * self.integral_error + self.kd * derivative_error

        return PID_output