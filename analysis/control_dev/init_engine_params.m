%% Parameters for Throttleable Engine Model

% Run Lookup Table Scripts
run("cstar_lookup_table.m")
run("sonvel_lookup_table.m")

% Unit conversions
psi_to_Pa = 6894.76;
in_to_m = 0.0254;

% Ambient Pressure
P_amb = 101325; % [Pa]

% Design values
P_c_nom = 350 * psi_to_Pa; % [Pa] max chamber pressure. source: Engine + Feed Speccing Sheet
P_c_min = 270 * psi_to_Pa; % [Pa] min desired chamber pressure. source: Engine + Feed Speccing Sheet
OF = 1.2; % ox fuel ratio. source: Engine + Feed Speccing Sheet

% Liquid Propellant Properties
rho_f = 789; % [kg/m^3] ethanol density. source: google
rho_ox = 988.82; % [kg/m^3] liquid N2O density at 0 F, const T before combustion chamber. source: Engine + Feed Speccing Sheet
K_f = 1.06e9; % [Pa] NEEDS DOUBLE CHECK room temp ethanol bulk modulus 
K_ox = 1.8e9; % [Pa] NEEDS DOUBLE CHECK 0F liquid N2O bulk modulus 
%%%% Calculate nominal propellant flow rates
mdot_nom = 0.3; % [kg/s] nominal/max/fully open mdot total. source: Engine + Feed Speccing Sheet
mdot_f_nom = mdot_nom / (1 + OF); % [kg/s] nominal/max/fully open mdot_f
mdot_ox_nom = mdot_nom * OF / (1 + OF); % [kg/s] nominal/max/fully open mdot_ox
%%%% Calculate minimum propellant flow rates
mdot_min = 0.85*0.3; % [kg/s] minimum thorttle mdot total.
mdot_f_min = mdot_min / (1 + OF); % [kg/s] minimum throttle mdot_f
mdot_ox_min = mdot_min * OF / (1 + OF); % [kg/s] minimum throttle mdot_ox

% Engine Parameters
V_c = 2.5335373958699e-4; % [m^3] chamber volume. source: Engine + Feed Speccing Sheet
A_t = 1.266768698e-4; % [m^2] throat area. source: Engine + Feed Speccing Sheet
tau_c = 5e-3; % [s] combustion/mixing time scale ??how do I choose this accurately??

% Injector Parameters
DeltaP_inj_percent = 20; % [% of P_c_nom]. source: Engine + Feed Speccing Sheet
DeltaP_inj = DeltaP_inj_percent / 100 * P_c_nom; % [Pa] Delta P across injector for both propellants
%%%% Geometry
ID_inj_elem_ox = 0.05; % [in] ID of an ox injector element
ID_inj_elem_f = 0.052; % [in] ID of a fuel injector element
A_inj_elem_ox = pi*(ID_inj_elem_ox/2)^2; % [in^2] area of an ox injector element
A_inj_elem_f = pi*(ID_inj_elem_f/2)^2; % [in^2] area of a fuel injector element
N_inj_elem = 8; % number of injector elements, both fuel and ox
A_inj_ox = A_inj_elem_ox * N_inj_elem * in_to_m^2; % [m^2] total area of ox injector
A_inj_f = A_inj_elem_f * N_inj_elem * in_to_m^2; % [m^2] total area of ox injector
%%%% Cd_inj for propellants
Cd_inj_f = 0.6; % need test data
Cd_inj_ox = 0.6; % need test data

% Feed Pressures
P_tank_f = 3242543.676; % [Pa] fuel feed pressure, constant because regulated with N2. source: Engine + Feed Speccing Sheet
P_tank_ox = 3260949.847; % [Pa] ox feed pressure, constant because regulated with N2. source: Engine + Feed Speccing Sheet
DeltaP_lines_f = 33.2 * psi_to_Pa; % [Pa] source: Engine + Feed Speccing Sheet
DeltaP_lines_ox = 36 * psi_to_Pa; % [Pa] source: Engine + Feed Speccing Sheet
P_1_f = P_tank_f - DeltaP_lines_f; % [Pa] fuel feed pressure
P_1_ox = P_tank_ox - DeltaP_lines_ox; % [Pa] ox feed pressure

% Line between valves and injector
r_line = 0.5 * in_to_m; % [m] line radius
A_line = pi*r_line^2; % [m^2} line area
L_line = 24 * in_to_m; % [m] line length
V_line = A_line * L_line; % [m^3] line volume
C_ox = K_ox / (rho_ox * V_line); % Ox compressibility term
C_f = K_f / (rho_f * V_line); % Fuel compressibility term

% Dynamics Parameters
%%%% Servo-valve
k_servo = 1; % servo DC gain
tau_servo = 0.05; % [s] servo time constant
%%%% Chamber
a = -5;
b = 6.7e7;
k_chamber = -b/a;
tau_chamber = -1/a;



