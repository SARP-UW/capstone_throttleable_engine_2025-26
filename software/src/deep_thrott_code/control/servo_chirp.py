import numpy as np
from scipy.signal import chirp
import matplotlib.pyplot as plt

# Parameters
T = 10.0             # Total time in seconds
fs = 1000           # Sampling frequency (Hz)
f0 = 0.01             # Start frequency (Hz)
f1 = 2            # End frequency 1 (Hz)
f2 = 5            # End frequency 2 (Hz)
f3 = 10            # End frequency 3 (Hz)
f4 = 20            # End frequency 4 (Hz)
t = np.linspace(0, T, int(T * fs), endpoint=False)

# Generate linear chirp
# method options: 'linear', 'quadratic', 'logarithmic'
chirp_2hz = chirp(t, f0=f0, t1=T, f1=f1, method='linear')
chirp_5hz = chirp(t, f0=f0, t1=T, f1=f2, method='linear')
chirp_10hz = chirp(t, f0=f0, t1=T, f1=f3, method='linear')
chirp_20hz = chirp(t, f0=f0, t1=T, f1=f4, method='linear')
chirp_angle_2hz = 45*chirp_2hz + 45
chirp_angle_5hz = 45*chirp_5hz + 45
chirp_angle_10hz = 45*chirp_10hz + 45
chirp_angle_20hz = 45*chirp_20hz + 45

# Plot
plt.plot(t, chirp_angle_10hz)
plt.title("Linear Chirp Sine Wave")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude (Degrees)")
plt.show()
