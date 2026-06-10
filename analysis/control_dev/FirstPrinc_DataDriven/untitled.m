% Time vector (8 seconds, 1 kHz sample rate)
dt = 0.001;
t = 0:dt:8;

% Commanded pressure: 350 psi for 4s, then 280 psi
Pc_cmd = 350*ones(size(t));
Pc_cmd(t >= 4) = 280;

% --- Generate "measured" chamber pressure ---

% Startup transient: exponential rise from atmospheric to 350 psi
Pc_startup = 14.7 + (350 - 14.7)*(1 - exp(-t/0.25));  % ~250 ms time constant

% After 4 seconds: exponential decay from 350 → 280 psi with <2s settling
Pc_stepdown = 280 + (350 - 280)*exp(-(t-4)/0.7);  % ~0.7s time constant
Pc_stepdown(t < 4) = 350;  % only apply after 4s

% Combine startup + stepdown
Pc_meas = Pc_startup;
Pc_meas(t >= 4) = Pc_stepdown(t >= 4);

% Add realistic noise (band‑limited)
noise = 3*randn(size(t));  % ±3 psi-ish
Pc_meas = Pc_meas + noise;

% Optional: ensure no negative values
Pc_meas = max(Pc_meas, 0);

% Plot
figure; hold on;
plot(t, Pc_cmd, 'LineWidth', 2);
plot(t, Pc_meas, 'LineWidth', 1.5);
xlabel('Time [s]');
ylabel('Chamber Pressure [psi]');
legend('Commanded', 'Measured');
title('[FAKE DATA] Commanded and Measured Chamber Pressure')
grid on;
