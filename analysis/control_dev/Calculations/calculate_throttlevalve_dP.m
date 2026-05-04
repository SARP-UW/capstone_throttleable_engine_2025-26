% Load parameters from parameters script into workspace
run("init_engine_params.m")

% flow coeff of a given valve
Cv_max = .7;

% find volumetric flow rate
Q_ox_nom = mdot_ox_nom / rho_ox; % [m^3/s]

% convert Q to gallons per minute
m3s_to_gpm = 15850.37248;
Q_ox_nom_gpm = Q_ox_nom * m3s_to_gpm;

% calculate specific gravity
SG_ox = rho_ox/1000; % density over density of water

% calculate dP across valve for given Cv and mdot
dP = SG_ox * Q_ox_nom_gpm^2 / Cv_max^2