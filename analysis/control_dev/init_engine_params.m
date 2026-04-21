%% Parameters for Throttleable Engine Model

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

% Engine Parameters
V_c = 2.5335373958699e-4; % [m^3] chamber volume. source: Engine + Feed Speccing Sheet
A_t = 1.266768698e-4; % [m^2] throat area. source: Engine + Feed Speccing Sheet
tau_c = 5e-3; % [s] combustion/mixing time scale ??how do I choose this accurately??

% Injector Parameters
DeltaP_inj_percent = 20; % [% of P_c_nom]. source: Engine + Feed Speccing Sheet
DeltaP_inj = DeltaP_inj_percent / 100 * P_c_nom; % [Pa] Delta P across injector for both propellants
%%%% Calculate nominal propellant flow rates
mdot_nom = 0.3; % [kg/s] nominal/max/fully open mdot total. source: Engine + Feed Speccing Sheet
mdot_f_nom = mdot_nom / (1 + OF); % [kg/s] nominal/max/fully open mdot_f
mdot_ox_nom = mdot_nom * OF / (1 + OF); % [kg/s] nominal/max/fully open mdot_ox
%%%% Calculate CdA_inj for propellants
CdA_inj_f = mdot_f_nom / sqrt(2 * rho_f * DeltaP_inj);
CdA_inj_ox = mdot_ox_nom / sqrt(2 * rho_ox * DeltaP_inj);

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

% Look up tables
%%%% P_c_ref to theta_ox_des
% Breakpoints (P_c_ref in Pa)
P_c_ref_bp = [0, 5e5, 1e6, 1.5e6, 2e6];
% Corresponding valve angles (deg)
theta_ff_table = [0,  10,   25,   40,   55];
%%%% Valve angle to CdA
% Valve angle breakpoints (deg)
theta_bp = [0   5    10    15    20    30    40    50    60];
% Corresponding CdA values (m^2)
CdA_table = [0, ...
             1e-6, ...
             4e-6, ...
             8e-6, ...
             1.5e-5, ...
             3.5e-5, ...
             6.0e-5, ...
             8.2e-5, ...
             1.0e-4];
