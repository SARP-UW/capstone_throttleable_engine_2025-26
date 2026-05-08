% Unit conversions
psi_to_Pa = 6894.76;

Pc_vec = psi_to_Pa*readmatrix('cstar_lookup_table.xlsx','Range','B3:B23');

OF_vec = readmatrix('cstar_lookup_table.xlsx','Range','C2:I2');


cstar_matr = readmatrix('cstar_lookup_table.xlsx','Range','C3:I23');
