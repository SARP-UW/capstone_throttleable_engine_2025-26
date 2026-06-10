% Conversion factor
in_to_m = 0.0254; % inch to meter conversion

% Load parameters from parameters script into workspace
run("init_engine_params.m")

% Calculate Re for water cold flow
rho_w = 998.2; % [kgs/s] density of water at 20 C
D_line_sys = 3/8 * in_to_m; % [m] ID of line to throttle valve
A_line_sys = pi*(D_line_sys/2)^2; % [m^2] area of line to throttle valve
mdot_w = 0.7; % [kg/s] mass flow rate NEED REAL DATA
v_w = mdot_w/(rho_w * A_line_sys); % [m/s] average water velocity
mu_w = 1.002e-3; % [Pa*s] dynamic viscosity of water at 20 C
Re_w = (rho_w * v_w * D_line_sys) / mu_w; % Reynolds number for water flow

% Calculate Re for ox in real system
v_ox_nom = mdot_ox_nom/(rho_ox * A_line_sys); % [m/s] average ox velocity at full throttle
v_ox_min = mdot_ox_min/(rho_ox * A_line_sys * 0.85); % [m/s] average ox velocity at 85% throttle
mu_ox = 1.3332e-4; % [Pa*s] dynamic viscosity of N2O at 0 F
Re_ox_nom = (rho_ox * v_ox_nom * D_line_sys) / mu_ox; % Reynolds number for ox in real sys conditions
Re_ox_min = (rho_ox * v_ox_min * D_line_sys * sqrt(0.85)) / mu_ox; % Reynolds number for ox in real sys conditions at 85% throttle
% simplifying valve geometry change as if orifice remains circular and diameter can be measured


% Calculate Re for fuel in real system
v_f_nom = mdot_f_nom/(rho_f * A_line_sys); % [m/s] average ox velocity at full throttle
v_f_min = mdot_f_min/(rho_f * A_line_sys * .85); % [m/s] average ox velocity at 85% throttle
mu_f = 1.25e-3; % [Pa*s] dynamic viscosity of ethanol  at 20 C
Re_f_nom = (rho_f * v_f_nom * D_line_sys) / mu_f; % Re for ox in real sys conditions, full throttle
Re_f_min = (rho_f * v_f_min * D_line_sys * sqrt(0.85)) / mu_f; % Reynolds number for ox in real sys conditions at 85% throttle
% simplifying valve geometry change as if orifice remains circular and diameter can be measured

% Calculate Re for ox in injector
v_ox_inj_nom = mdot_ox_nom/(rho_ox * A_inj_elem_ox * in_to_m^2);
v_ox_inj_min = mdot_ox_min/(rho_ox * A_inj_elem_ox * in_to_m^2);
Re_ox_inj_nom = (rho_ox * v_ox_inj_nom * ID_inj_elem_ox) / mu_ox; % Re for ox injector, full throttle
Re_ox_inj_min = (rho_ox * v_ox_inj_min * ID_inj_elem_ox) / mu_ox; % Re for ox injector, 85% thorttle

% Calculate Re for ox in injector
v_f_inj_nom = mdot_f_nom/(rho_f * A_inj_elem_f * in_to_m^2);
v_f_inj_min = mdot_f_min/(rho_f * A_inj_elem_f * in_to_m^2);
Re_f_inj_nom = (rho_f * v_f_inj_nom * ID_inj_elem_f) / mu_f; % Re for ox injector, full throttle
Re_f_inj_min = (rho_f * v_f_inj_min * ID_inj_elem_f) / mu_f; % Re for ox injector, 85% thorttle