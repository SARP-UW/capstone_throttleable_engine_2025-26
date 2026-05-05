import numpy as np
from scipy.signal import chirp
import matplotlib.pyplot as plt

# Parameters
T = 2.0             # Total time in seconds
fs = 1000           # Sampling frequency (Hz)
f0 = 10             # Start frequency (Hz)
f1 = 200            # End frequency (Hz)
t = np.linspace(0, T, int(T * fs), endpoint=False)

# Generate linear chirp
# method options: 'linear', 'quadratic', 'logarithmic'
y = chirp(t, f0=f0, t1=T, f1=f1, method='linear')

# Plot
plt.plot(t, y)
plt.title("Linear Chirp Sine Wave")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude")
plt.show()
