%% Parameters for Throttleable Engine Model

% Ambient Pressure
P_amb = 14.7; % [psi] ambient pressure

% Engine Parameters
V_c = 0.2; % [m^3] chamber volume
A_t = 0.002; % [m^2] throat area

% Injector Parameters
V_plenum_f = 0.02; % [m^3] fuel plenum volume
V_plenum_ox = 0.02; % [m^3] ox plenum volume
CdA_inj_f = 0.7; % CdA for fuel injector ??need to model better than constant??
CdA_inj_ox = 0.7; % CdA for fuel injector ??need to model better than constant??

% Feed Pressures
P_tank_f = 500; % [Psi] fuel feed pressure, constant because regulated with N2
P_tank_ox = 500; % [Psi] ox feed pressure, constant because regulated with N2

% Liquid Propellant Properties
rho_f = 789; % [kg/m^3] ethanol density
rho_ox = 750; % [kg/m^3] ??const T before combustion chamber?? liquid N2O density, temp depedent
a_liq_f = 1144; % [m/s] speed of sound in liquid ethanol, source: Link #8
a_liq_ox = 263; % [m/s] ??varies with temp?? speed of sound in liquid nitrous oxide

% Set nominal DeltaP and mdot
DeltaP_nom = 70; % [psi]
mdot_nom = 0.1; % [psi]

% Set CdAmax for initial Cd tuning
% not really sure about this method, need to learn more about Cd
% why does injector geometry not show up here?
% Fuel:
C_d_f = 0.7; % starting estimate
A_eff_f = mdot_nom / (C_d_f * sqrt(2 * rho_f * DeltaP_nom));
CdA_max_valve_f = C_d_f * A_eff_f;
% Ox:
C_d_ox = 0.7; % starting estimate
A_eff_ox = mdot_nom / (C_d_ox * sqrt(2 * rho_ox * DeltaP_nom));
CdA_max_valve_ox = C_d_ox * A_eff_ox;




