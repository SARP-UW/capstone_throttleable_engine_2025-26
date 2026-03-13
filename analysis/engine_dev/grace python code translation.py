## translating Grace's heat transfer code to python

#import numpy as np
#import matplotlib as plt
#import scipy as scp
import math

pi = math.pi


# thermal conductivity 
k_ss = 14 # 17-4 for 800 F
k_a = 237 # aluminum
k_w = 0.55 # water [W/m*K]
# water props 
mu_w = 0.0017855 # viscosity water m^2/s 0 C
mu_w_wall = 0.0001102 # viscosity water m^2/s at wall temp, adjusted based on output
cp_w = 4.22e3 # specific heat water, j/kg/K 0 C


# data for OF ratio of 4.3 and P_c = 400 psi from CEA
rho_c = 2.7925 # kg/m^3
gamma_c = 1.23 
MW = 25.5 * 1/10**3 # molecular weight, kg/kmol
cp_g = 1.7425e3
c_star = 1518.1 # throat
g = 9.81 # gravity [m/s^2]
Pr_g = .6753
mu_g = 0.95386*0.0001
k_gas = 2.4612 * 1/10**3 * 10**2 # from cea, gas thermal conductivity 

"""
% % design inputs // if u unsupress there are mdot and wall thickness grap
% n = 50;
% mdot_w = .2; 
% % t = 2*10^-3; % wall thickness (m)
% t = linspace(0.5*10^-3,10*10^-3,n)
% r_channel = 3*10^-3; % radius of channels
% d_t = 9.4 * 10^-3; % diameter throat
% d_c = 51.6 * 10^-3; % diameter chamber
% P_c = 400 * 6894.76; % chamber press (Pc)
% rc_t = 1.8*10^-3; % radius curvature throat
% sigma = 1.1; % randomish correction factor for flat (chamber) section
% 
% % CHAMBER heat coefficients
% rho_w = 999.89;
% u_w = mdot_w/rho_w/(pi*r_channel^2)
% Re_w = rho_w*u_w*2*r_channel/mu_w
% Pr_w = cp_w*mu_w/k_w
% 
% hg = (0.026/(d_t^0.2) * ( mu_g^0.2 * cp_g / (Pr_g^0.6) ) * (P_c / c_star)^0.8 *...
%     (d_t/rc_t)^0.1) * ( pi*(d_t/2)^2 / (pi*(d_c/2)^2) )^0.9 * sigma %bartz
% 
% Nu_w = 0.027*Re_w^(4/5)*Pr_w^(1/3) * (mu_w/mu_w_wall)^0.14
% hw = Nu_w*( k_w / (2*r_channel) )
% 
% % CHAMBER heat calcs 
% T_gas = 2800; % K, chamber temp
% % T_water = 273; % K, water temp
% T_wall_gas = 500+273; %k chamber WALL temp
% r = (Pr_g)^(1/3);
% T_aw_gas = T_gas*(2+r*(gamma_c-1))/(gamma_c+1); %adiabatic wall temperature (??)
% 
% qtot = (T_gas-T_wall_gas)/(1/hg)
% T_wall_water = T_wall_gas - qtot*(t/k_ss)
% T_water = T_wall_water - ones(1,n)*qtot*(1/hw) 
% 
% plot(t*10^3,T_water-273)
% xlabel('wall thickness (mm)')
% ylabel('temperature of water (C) to achieve 500C gas-side wall')
% 
% mdot_w = linspace(0.05,2,n); 
% t = 5*10^-3; % wall thickness (m)
% u_w = mdot_w/rho_w/(pi*r_channel^2)
% Re_w = rho_w*u_w*2*r_channel/mu_w
% Nu_w = 0.027*Re_w.^(4/5)*Pr_w^(1/3) * (mu_w/mu_w_wall)^0.14
% hw = Nu_w*( k_w / (2*r_channel) )
% qtot = (T_gas-T_wall_gas)/(1/hg)
% T_wall_water = T_wall_gas - qtot*(t/k_ss)
% T_water = ones(1,n)*T_wall_water - qtot*(1./hw) 
% 
% figure
% plot(mdot_w,T_water-273)
% xlabel('mdot')
% ylabel('temperature of water (C) to achieve 500C gas-side wall')
% 
% % % qtot = (T_gas - T_water)/(1/hg + t/(k_ss) + 1/hw) % total heat per area
% % % T_wall_gas = T_gas - qtot*(1/(hg)) % temperature of surface gas side
% % % T_wall_water = T_wall_gas - t/k_ss*qtot % temperature of the surface on the water side
% 
% mdot_w = 0.1;
% t = 4.5 * 10^-3;
% u_w = mdot_w/rho_w/(pi*r_channel^2)
% Re_w = rho_w*u_w*2*r_channel/mu_w
% Nu_w = 0.027*Re_w.^(4/5)*Pr_w^(1/3) * (mu_w/mu_w_wall)^0.14
% hw = Nu_w*( k_w / (2*r_channel) )
% qtot = (T_gas-T_wall_gas)/(1/hg)
% T_wall_water = T_wall_gas - qtot*(t/k_ss)
% T_water = T_wall_water - qtot*(1./hw) -273 """

# weronika input here!!!!!!!!

# design inputs
mdot_w = .2
t = 4.5e-3 # wall thickness (m)  <------ adjust wall thickness here
r_channel = 3e-3 # radius of channels
d_t = 9.4e-3 # diameter throat
d_c = 51.6e-3 # diameter chamber
P_c = 400 * 6894.76 # chamber press (Pc)
rc_t = 1.8e-3 # radius curvature throat
sigma = 1.1 # randomish correction factor for flat (chamber) section

# CHAMBER heat coefficients
rho_w = 999.89
u_w = mdot_w/rho_w/(pi*r_channel**2)
Re_w = rho_w*u_w*2*r_channel/mu_w
Pr_w = cp_w*mu_w/k_w

# bartz
hg = (0.026/(d_t**0.2)*(mu_g**0.2*cp_g/(Pr_g**0.6))*(P_c/c_star)**0.8*(d_t/rc_t)**0.1)*(pi*(d_t/2)**2/(pi*(d_c/2)**2))**0.9*sigma

Nu_w = 0.027*Re_w**(4/5)*Pr_w**(1/3) * (mu_w/mu_w_wall)**0.14
hw = Nu_w*( k_w / (2*r_channel) )

# CHAMBER heat calcs /// currently 1 dimensional and per area / heat flux
T_gas = 2800 # K, chamber temp
# T_water = 273 # K, water temp
T_wall_gas = 500+273 # K, chamber WALL temp
r = (Pr_g)**(1/3)
T_aw_gas = T_gas*(2+r*(gamma_c-1))/(gamma_c+1); # adiabatic wall temperature (??)

qtot = (T_gas-T_wall_gas)/(1/hg)
T_wall_water = T_wall_gas - qtot*(t/k_ss)
T_water = T_wall_water - qtot*(1/hw) 


# outputs

print("u_w = " + str(u_w))
print("Re_w = " + str(Re_w))
print("Pr_w = " + str(Pr_w))
print("hg = " + str(hg))
print("Nu_w = " + str(Nu_w))
print("hw = " + str(hw))
print("qtot = " + str(qtot))
print("T_wall_water = " + str(T_wall_water))
print("T_water = " + str(T_water))

