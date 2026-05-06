import matplotlib.pyplot as plt
import numpy as np

dt = 0.001          # sample time (1 kHz logging is ideal)
t_hold = 3.0        # seconds to hold each command

# Time vectors for each segment
t0 = np.arange(0, t_hold, dt)
t1 = np.arange(0, t_hold, dt)
t2 = np.arange(0, t_hold, dt)
t3 = np.arange(0, t_hold, dt)
t4 = np.arange(0, t_hold, dt)

# Command levels
cmd0 = np.zeros_like(t0)          # 0 degrees
cmd1 = np.ones_like(t1) * 10      # 10 degrees
cmd2 = np.ones_like(t2) * 30      # 30 degrees
cmd3 = np.ones_like(t3) * 60      # 60 degrees
cmd4 = np.zeros_like(t4)          # back to 0 degrees

# Concatenate into one command profile
time = np.concatenate([
    t0,
    t0[-1] + t1,
    t0[-1] + t1[-1] + t2,
    t0[-1] + t1[-1] + t2[-1] + t3,
    t0[-1] + t1[-1] + t2[-1] + t3[-1] + t4
])

command = np.concatenate([cmd0, cmd1, cmd2, cmd3, cmd4])

# Plot
plt.plot(time, command)
plt.title("Piecewise Angle Commands")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude (Degrees)")
plt.show()
