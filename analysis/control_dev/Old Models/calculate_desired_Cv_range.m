%% Calculate range of Cv values for throttle valves

% Load parameters from parameters script into workspace
run("init_engine_params.m")

% Calculate injector inlet pressure
P_inj_in = P_c_nom + DeltaP_inj;

% Calculate pressure drop across valves
DeltaP_valve_f = P_feed_f - P_inj_in;
DeltaP_valve_ox = P_feed_ox - P_inj_in;
CdA_max_valve_f = mdot_f_nom / sqrt(2 * rho_f * DeltaP_valve_f);
CdA_max_valve_ox = mdot_ox_nom / sqrt(2 * rho_ox * DeltaP_valve_ox);

% Calculate volumetric flow rate
Q_f = CdA_max_valve_f * sqrt(2 * DeltaP_valve_f / rho_f); % [m^3/s]
Q_ox = CdA_max_valve_ox * sqrt(2 * DeltaP_valve_ox / rho_ox); % [m^3/s]

% Convert Q to gallons per minute
Q_gpm_f = Q_f * 1000 / 3.78541 * 60; % [gpm]
Q_gpm_ox = Q_ox * 1000 / 3.78541 * 60; % [gpm]

% Convert DeltaP_valves to psi
DeltaP_valve_f_psi = DeltaP_valve_f / psi_to_Pa; % % [psi]
DeltaP_valve_ox_psi = DeltaP_valve_ox / psi_to_Pa; % [psi]

% Calculate specific gravity
G_f = rho_f/1000; % density over density of water
G_ox = rho_ox/1000; % ''

% Calculate Cv at fully open state
Cv_open_f = Q_gpm_f / sqrt(DeltaP_valve_f_psi / G_f);
Cv_open_ox = Q_gpm_ox / sqrt(DeltaP_valve_ox_psi / G_ox);

% Calculate lowest mass flow
c_star_P_c_min = 1207.7; % [m/s] calculated with CEA at P_c = 270 psi, OF = 1.2
mdot_min = P_c_min * A_t / c_star_P_c_min;

% Calculate min propellant flow rates
mdot_f_min = mdot_min / (1 + OF); % [kg/s] nominal/max/fully open mdot_f
mdot_ox_min = mdot_min * OF / (1 + OF); % [kg/s] nominal/max/fully open mdot_ox

% Calculate mininum volumetric flow rates
Q_min_f = mdot_f_min / rho_f; % [m^3/s]
Q_min_ox = mdot_ox_min / rho_ox; % [m^3/s]

% Convert Q to gallons per minute
Q_gpm_min_f = Q_min_f * 1000 / 3.78541 * 60; % [gpm]
Q_gpm_min_ox = Q_min_ox * 1000 / 3.78541 * 60; % [gpm]

% Calculate Cv at fully open state, assume DeltaP_valve is same
Cv_min_f = Q_gpm_min_f / sqrt(DeltaP_valve_f_psi / G_f);
Cv_min_ox = Q_gpm_min_ox / sqrt(DeltaP_valve_ox_psi / G_ox);

%%%% result: lower Cv_min = 0.3951, higher Cv_open = 0.6333
