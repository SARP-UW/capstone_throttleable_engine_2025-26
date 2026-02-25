## CAPSTONE ENGINE STRUCTURAL ANALYSIS ##

# import statements #
import numpy as np
import matplotlib.pyplot as plt
import scipy as scp
import math


# mathematical constants #
pi = math.pi

## PARAMETERS ##

# thrust chamber parameters #
T_tc = 2956 # chamber temperature, [K] 
T_aw = 1413 # max gas side wall temp, [K], from SCA
Pg = 300*6894.76 #2.137374757e6  # gas pressure, [Pa]
OF = 4 
q = 9621.5436*1000 #25486.222200034565*1000 # W/m^2 # max heat flux from chamber, at throat
t2 = 1/1000 # wall thickness, [m]
hg = 24000 # convective heat transfer gas [W/m^2/K], from RPA
V = 253353.73958699e-9 # volume, [m^3]
r_g = 2.1056 # kg/m^3 aka rho_c
g_g = 1.1741 # gamma_c 
MW = 0.02506 *(1/1000) # molecular weight, kg/mol, 
Cp_g = 3.0367*1000 # J/kg*K
Cstar = 1498.000558 # throat, m/s
g = 9.81 # gravity [m/s^2]
Pr_g = 0.6696
mu_g = 9.332e-05 # viscosity gas, kg/m*s
k_g = 0.2456  # from rpa, frozen gas thermal conductivity, k_gas 
r = 0.0254 # chamber inner radius, [m]
FOS = 2
R = 8.314/MW
L = 0.16 # engine length, 6.3" in [m]


# 17-4 parameters # --> recheck for 17-4 H900

k_tc = 22.7 # thermal conductivity, [W/m*K] for 21-500 deg C
v = 0.272 # poisson ratio
E = 196e9 # young's modulus, [Pa], could be up to 207
S_ult = 1030e6 # ultimate strength, [Pa]
S_y = 760e6 # yield stress, [Pa]
# D = # stiffness matrix
a = 11.3e-6 # thermal expansion coefficient, [m/m*K], for +21C to +427C
r_tc = 7.75*1000 # mass density, [kg/m^3] 
Cp_tc = 480 # specific heat, [J/kg*K]
T_melt = 1677 # melting temperature, [K]
T_ref = 293 # room temp, [K]

# cooling channel parameters #  CHANGE LATER ARBITRARY NOW

t1 = 2*.001 # wall thickness, [m]
l = 4*.001 # width cooling channel, [m]
tl = 2*.001 # height cooling channel, [m]
n = 40 # number channels

# hydraulic diameter (for rectangular duct) #
d_h = (2*l*tl)/((l+tl))


# coolant parameters #

k_l = 0.55 # water thermal conductivity [W/m*K]
Tb_l = 100 + 273.15 # water boiling point, [K]
Ti_l = 274 # initial water temp, [K]
hl = 2.76e5 # W/m^2/K, liquid
Pl = 3000*6894.76 # coolant pressure in channel, [Pa] aka 300 psi
Tl = 322 # max coolant temp in channel, [K]
Cp_l = 4.22e3 # specific heat water, [J/kg*K] @ 0 C 
mu_w = 0.0017855 # viscosity water [m^2/s] @ 0 C
mu_w_wall = 0.0001102 # viscosity water [m^2/s] @ wall temp, adjusted based on output
r_l = 1000 # density water, [kg/m3]
V_l = 1 # coolant velocity, [m/s2] ARBITRARY NEED TO CALCULATE





## STRESS AND STRAIN ##
#eps = eps_el + eps_pl + eps_th # total strain
# e_th = a*(T_aw-T_ref)*(111000)**T_aw # thermal strain --> getting overflow error
# need s max
s_hoop = (Pg*r)/t2
s_ax = (Pg*r)/(2*t2)
s_therm = (E*a*(T_aw-T_ref))/(1-v) #fully restrained assumption  -> assuming restrained by surrounding material
s_total = s_hoop+s_therm # in hoop dir


"""
if S_ult/s_hoop<FOS:
    print("The chamber fails due to hoop stress.")
else: 
    print("The chamber doesn't fail due to hoop stress. The FOS is: " + str(round(S_ult/s_hoop,2)))
"""
## todo: hydraulic diameter --> then huzel eqs, mit eqs for coolant channels


#print ("hoop stress [Pa]: "+str(s_hoop)) # not very useful 
#print ("axial stress [Pa]: "+str(s_ax))
print ("thermal stress [MPa]: "+str(s_therm*10**-6))

## FAILURE MODES ##

# low cycle fatigue #
Nf = 30 # 15 cycles with FOS 2?

c_f = -0.7 # fatigue ductility exponent for am 17-4 (check later kinda sus)
e_f = .35 # fatigue ductility coeff for am 17-4 also kinda sus, put H900 for now

# e_a = (s_f/E)*(2*Nf)**b + e_f*(2*Nf)**c_f # smith watson topper
e_a = e_f*(2*Nf)**c_f # coffin manson
print("strain amplitude: "+ str(e_a))

# buckling #

# critical stress for longitudinal inelastic buckling

# bursting #

P_b = (2*S_ult*t2)/(2*(r+t2)) # barlow formula
print("burst pressure [Pa]: "+ str(P_b)) 

# creep #

# huzel cooling channel analysis #
s_t = (((Pl-Pg)*(d_h/2))/t1) + ((E*a*q*t1)/(2*k_tc*(1-v)))
print("tangential stress in circular tube [MPa]: "+ str(s_t*10**-6)) 


# mit pdf stuff # 
s_1 = S_ult/FOS
s_2h = E*s_1-(a*E/(1-v))*((1/hl)+(t2/k_tc))*q-(E*a*(Tl-T_ref)/(1-v))
print("s_2h: "+ str(s_2h))
s_2b = ((pi**2)/3)*((t2/l)**2)*E
print("s_2b [MPa]: "+ str(s_2b*10**-6))

# new thermal stress
Sc=(((Pl-Pg)*r)/t2)+(E*a*q*t2)/(2*k_tc*(1-v))
print("combined max compressive stress [MPa]: "+str(Sc*10**-6))


## solving for thickness instead
thick = np.linspace(.4/1000, 2/1000, 100)
Sc_2=((((Pl-Pg)*r)/thick)+(E*a*q*thick)/(2*k_tc*(1-v)))*10**-6
#plt.figure(figsize=(8, 6)) 
plt.plot(thick, Sc_2, label='max compressive stress')
plt.axhline(y=S_ult*10**-6, color='r', linestyle='--', label='ultimate strength') 
plt.axhline(y=S_y*10**-6, color='orange', linestyle='--', label='yield strength') #
plt.title('max compressive stress vs thickness')
plt.xlabel('Thickness (m)') # x-axis
plt.ylabel('Compressive stress (MPa)') # y-axis
plt.grid(True) 
plt.legend() 
plt.show() 

# pressure drop in cooling passages
f = 2 # friction loss coeff, ARBITRARY NEED TO CALCULATE
dP = f*(L/d_h)*((r_l*(V_l**2))/(2*g))

# comprehensive analysis plan: 
    # input thickness
    # cycle through various failure modes
    # check failure for each and return if it fails or if it doesn't, then fos
    
    
def huzel_structural_failure(t_iw):
    results = [0,0,0,0,0]
    
    