import numpy as np
from scipy.signal import chirp
import matplotlib.pyplot as plt

# Parameters
T = 10.0             # Total time in seconds
fs = 1000           # Sampling frequency (Hz)
f0 = 0.01             # Start frequency (Hz)
f1 = 10            # End frequency (Hz)
t = np.linspace(0, T, int(T * fs), endpoint=False)

# Generate linear chirp
# method options: 'linear', 'quadratic', 'logarithmic'
chirp_general = chirp(t, f0=f0, t1=T, f1=f1, method='linear')
chirp_angle = 45*chirp_general + 45

# Plot
plt.plot(t, chirp_angle)
plt.title("Linear Chirp Sine Wave")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude (Degrees)")
plt.show()
