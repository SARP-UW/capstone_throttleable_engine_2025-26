

class PID:
    """
    Basic PID class
    """

    def __init__(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd

    def PID_output(self, reference, current_value, previous_value, dt):
        self.reference = reference
        self.current_value = current_value
        self.previous_value = previous_value
        self.dt = dt
        
        error = self.reference - self.current_value
        integral_error += error * self.dt
        derivative_error = (self.current_value - self.previous_value)/self.dt
        PID_output = self.kp * error + self.ki * integral_error + self.kd * derivative_error

        return PID_output