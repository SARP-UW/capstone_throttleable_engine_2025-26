%% Parameters for Throttleable Engine Model

% Ambient Pressure
P_amb = 14.7; % [psi] ambient pressure

% Engine Parameters
V_c = 0.2; % [m^3] chamber volume
A_t = 0.002; % [m^2] throat area

% Feed Pressures
P_feed_f = 500; % [Psi] fuel feed pressure
P_feed_ox = 500;% [Psi] ox feed pressure

% Liquid Propellant Densities
rho_f = 789; % [kg/m^3]
rho_ox = 750; % [kg/m^3] get temp to get correct rho

% Set nominal DeltaP and mdot
DeltaP_nom = 70; % [psi]
mdot_nom = 0.1; % [psi]

% Set CdAmax for initial Cd tuning
% not really sure about this method, need to learn more about Cd
% why does injector geometry not show up here?
% Fuel:
C_d_f = 0.7; % starting estimate
A_eff_f = mdot_nom / (C_d_f * sqrt(2 * rho_f * DeltaP_nom));
CdA_max_f = C_d_f * A_eff_f;
% Ox:
C_d_ox = 0.7; % starting estimate
A_eff_ox = mdot_nom / (C_d_ox * sqrt(2 * rho_ox * DeltaP_nom));
CdA_max_ox = C_d_ox * A_eff_ox;




