%% Calculate range of Cv values for throttle valves

% Design values
P_c_nom = 350; % [psi] max chamber pressure
P_c_min = 270; % [psi] min desired chamber pressure
mdot_nom = 0.27; % [kg/s] nominal/max/fully open mdot total
DeltaP_inj_percent = 20; % [% of P_c_nom]
DeltaP_inj = DeltaP_inj_percent / 100 * P_c_nom; % [psi] Delta P across injector for both propellants
OF = 1.2; % ox fuel ratio

% Calculate nominal propellant flow rates
mdot_f_nom = mdot_nom / (1 + OF); % [kg/s] nominal/max/fully open mdot_f
mdot_ox_nom = mdot_nom * OF / (1 + OF); % [kg/s] nominal/max/fully open mdot_ox

% Calculate CdA_inj for propellants
CdA_inj_f = mdot_f_nom / sqrt(2 * rho_f * DeltaP_inj);
CdA_inj_ox = mdot_ox_nom / sqrt(2 * rho_ox * DeltaP_inj);

%%%% find way to reference parameters file instead of redefining parameters %%%
