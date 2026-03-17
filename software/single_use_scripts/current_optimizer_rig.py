import os
import numpy as np
import pandas as pd
import cvxpy as cp
import matplotlib.pyplot as plt

# ============================================================
# Current Optimizer
# By: Andrew Hess
# ============================================================
# Purpose:
#   Find coil currents that minimize spherical harmonic coefficients (SHCs)
#   of a measured magnetic field inside the VOI.
# Strategy:
#   1) Fit baseline SHCs from measured DC field map
#   2) Use linear coil model
#   3) Solve weighted least-squares optimiation for currents
#   4) Enforce hardware limits (voltage, resistance, power)
#   5) Propagate uncertainty via Monte Carlo
# Note:
#   SHClabels use lab notation (B,G,C,D). Convert later to (l,m) manually.

date = "2026_01_28"

# -------------------- Paths --------------------
# SHC sensitivity matrix from tuning model
model_file = r"C:\Users\aweso\OneDrive\Documents\Data\Thesis Data\Results - Thesis Data\Tuning Results\tuning_model.npz"

# Baseline magnetic field measurement file
baseline_path = fr"C:\Users\aweso\OneDrive\Documents\Data\Thesis Data\Processed Data\Project Data\{date}\Field Map\DCfields.csv"

# Output saving path
output_path = fr"C:\Users\aweso\OneDrive\Documents\Data\Thesis Data\Results - Thesis Data\{date}\Optimizer Results"
os.makedirs(output_path, exist_ok=True)

# -------------------- Field uncertainty --------------------
# Per-axis sensor noise (nT)
field_uncert = [0.3, 0.03, 0.03]  # [Bx, By, Bz] uncertainties

# -------------------- Power limit (used for current bounds) --------------------
# Maximum allowed electrical power dissipated in any coil circuit 
# Meant to protect resistors and used to compute current limits
P_limit_W = 0.25

# -------------------- Optional: deactivate coils --------------------
# Remove coils by name without changing saved order
remove_list = []  # e.g. ["R4", "C3"]

# ============================================================
# SHC Fit (baseline only)
# ============================================================

def build_bmat_row(x, y, z, X, Y, Z):
    """
    Builds one row of the spherical harmonic design matrix

    Inputs
    -------
    (x,y,z) : sensor positions in shield coordinates relative to origin
    (X,Y,Z) : sensor orientation (unit vector)

    Outputs
    -------
    Row vector of 24 basis functions:
    [B(l=1), G(l=2), C(l=3), D(l=4)]

    Each entry is the projection of the analytic SH gradient basis 
    onto the sensor orientation.
    """

    #-----l=1 (uniform field)
    B1 = X; B2 = Y; B3 = Z

    #-----l=2 (first-order gradients)
    G1 = X*y + Y*x
    G2 = X*z + Z*x
    G3 = Y*z + Z*y
    G4 = -X*x - Y*y + 2*Z*z
    G5 = X*x - Y*y

    #-----l=3 (second-order gradients)
    C1 = X*6*x*y + Y*3*(x**2 - y**2)
    C2 = X*3*(x**2 - y**2) - Y*6*x*y
    C3 = X*y*z + Y*x*z + Z*x*y
    C4 = X*2*x*z - Y*2*y*z + Z*(x**2 - y**2)
    C5 = -X*2*x*y + Y*(4*z**2 - x**2 - 3*y**2) + Z*8*z*y
    C6 = X*(4*z**2 - 3*x**2 - y**2) - Y*2*x*y + Z*8*z*x
    C7 = -X*6*x*z - Y*6*y*z + Z*(6*z**2 - 3*(x**2 + y**2))

    #-----l=4 (third-order gradients)
    D1 = X*y*(3*x**2 - y**2) + Y*x*(x**2 - 3*y**2)
    D2 = X*6*x*y*z + Y*3*z*(x**2 - y**2) + Z*y*(3*x**2 - y**2)
    D3 = X*y*(6*z**2 - 3*x**2 - y**2) + Y*x*(6*z**2 - x**2 - 3*y**2) + Z*12*x*y*z
    D4 = X*6*x*y*z + Y*z*(3*x**2 + 9*y**2 - 4*z**2) + Z*y*(3*x**2 + 3*y**2 - 12*z**2)
    D5 = X*12*x*(x**2 + y**2 - 4*z**2) + Y*12*y*(x**2 + y**2 - 4*z**2) + Z*16*z*(2*z**2 - 3*x**2 - 3*y**2)
    D6 = X*z*(-9*x**2 - 3*y**2 + 4*z**2) - Y*6*x*y*z + Z*x*(-3*x**2 - 3*y**2 + 12*z**2)
    D7 = X*4*x*(x**2 - 3*z**2) - Y*4*y*(y**2 - 3*z**2) - Z*12*z*(x**2 - y**2)
    D8 = X*3*z*(x**2 - y**2) - Y*6*x*y*z - Z*(3*x*y**2 + x**3)
    D9 = X*4*x*(x**2 - 3*y**2) + Y*4*y*(y**2 - 3*x**2)
    return [B1, B2, B3, G1, G2, G3, G4, G5,
            C1, C2, C3, C4, C5, C6, C7,
            D1, D2, D3, D4, D5, D6, D7, D8, D9]

def compute_shc_and_uncert_from_dcfields_df(df, field_uncert):
    """
    Fits SHC coefficients from raw field map through weighted least squares
    """

    # sensor positions (converted to m)
    pts = df[['xPos', 'yPos', 'zPos']].to_numpy(dtype=float) / 1000.0
    # measured field components
    field = df[['Bx', 'By', 'Bz']].to_numpy(dtype=float)

    # stack measurements
    Br = np.concatenate([field[:, 0], field[:, 1], field[:, 2]])
    Npos = field.shape[0]
    N_measurements = Br.size

    # sensor orientations for each measurement
    xOri = np.tile([1, 0, 0], (Npos, 1))
    yOri = np.tile([0, 1, 0], (Npos, 1))
    zOri = np.tile([0, 0, 1], (Npos, 1))
    sens_pos = np.vstack([pts, pts, pts])
    sens_ors = np.vstack([xOri, yOri, zOri])

    # center coordinates to reduce conditioning issues
    origin = np.mean(sens_pos, axis=0)
    sens_pos = sens_pos - origin

    # build design matrix
    Bmat = np.array([
        build_bmat_row(*sens_pos[sample], *sens_ors[sample])
        for sample in range(N_measurements)
    ], dtype=float)

    # measurement weights
    sigma2 = np.concatenate([
        np.full(Npos, field_uncert[0] ** 2),
        np.full(Npos, field_uncert[1] ** 2),
        np.full(Npos, field_uncert[2] ** 2),
    ])
    W = np.diag(1.0 / sigma2)

    A = Bmat.T @ W @ Bmat
    rhs = Bmat.T @ W @ Br

    coeffs = np.linalg.solve(A, rhs)

    # covariance of coefficients
    Cov_coeffs = np.linalg.solve(A, np.eye(A.shape[0]))
    shc_uncert = np.sqrt(np.diag(Cov_coeffs))

    return coeffs, shc_uncert

# ============================================================
# Load tuning model (from tuning script)
# ============================================================
# slope given by change in SHC j per mA on coil k

model = np.load(model_file, allow_pickle=True)

coils_all = model["coils"].astype(object)             # coil order used in saved m
m_all = model["m"].astype(float)                      # shape: (Ncoils, 24)
m_unc_all = model["m_uncert"].astype(float)           # shape: (Ncoils, 24)
harmonic_labels = model["harmonic_labels"].astype(object)

# circuit electrical limits
coil_names_circ = model["coil_names"].astype(object)
Vmax_arr = model["Vmax"].astype(float)
Rmax_arr = model["Rmax"].astype(float)
Rmin_arr = model["Rmin"].astype(float)

circ_map = {
    str(name): {"Vmax": Vmax_arr[i], "Rmax": Rmax_arr[i], "Rmin": Rmin_arr[i]}
    for i, name in enumerate(coil_names_circ)
}

# remove diabled coils while preserving order
active_mask = np.array([c not in remove_list for c in coils_all])
coils = coils_all[active_mask]
m_mat = m_all[active_mask, :]          # (N, 24)
m_unc_mat = m_unc_all[active_mask, :]  # (N, 24)

# Build M in the optimizer convention: (24, N)
M = m_mat.T

# ============================================================
# Baseline SHCs
# ============================================================

baseline_df = pd.read_csv(baseline_path)
b_new, b_new_uncert = compute_shc_and_uncert_from_dcfields_df(baseline_df, field_uncert)
b_new = np.asarray(b_new, dtype=float)
b_new_uncert = np.asarray(b_new_uncert, dtype=float)

df_baseline = pd.DataFrame({
    "Harmonic": harmonic_labels,
    "Baseline SHC (New DCfields)": b_new,
    "Baseline Uncertainty": b_new_uncert
})
baseline_outfile = os.path.join(output_path, "baseline_SHCs.csv")
df_baseline.to_csv(baseline_outfile, index=False)
print(f"Baseline SHCs saved to: {baseline_outfile}")

# ============================================================
# Current bounds
# ============================================================
# Imax limited by:
#   1) voltage: Vmax / Rmin
#   2) power: sqrt(P / Rmin)

Imax_mA = np.zeros(len(coils), dtype=float)
for k, coil in enumerate(coils):
    c = circ_map[str(coil)]
    Imax_A = min(
        c["Vmax"] / c["Rmin"],
        np.sqrt(P_limit_W / c["Rmin"])
    )
    Imax_mA[k] = 1000.0 * Imax_A

# ============================================================
# Optimization: minimize weighted SHC residuals
# ============================================================

N = len(coils)
i = cp.Variable(N)

constraints = [i <= Imax_mA, i >= -Imax_mA]

K = 24
weights = np.ones(K)

# strongly penalize low-order terms (field + first-order gradients)
weights[0:3] = 10000   # l=1
weights[3:8] = 10000   # l=2
weights[8:15] = 1      # l=3
weights[15:24] = 1     # l=4

residual = cp.multiply(np.sqrt(weights), (M @ i + b_new))
objective = cp.Minimize(cp.sum_squares(residual))
prob = cp.Problem(objective, constraints)
prob.solve(solver=cp.SCS)

if i.value is None:
    raise RuntimeError(f"Optimization failed. Status: {prob.status}")

optimized_currents = np.asarray(i.value).ravel()
predicted_SHCs = M @ optimized_currents + b_new

# ======================================
# Monte Carlo uncertainty propagation
# ======================================
# Randomize:
#   baseline SHCs
#   coil sensitiviy rows
# Re-solve optimization many times

rng = np.random.default_rng(42)
Nmc = 2000

b_new_cov = np.diag(b_new_uncert**2)

# diagonal fallback (matches your current approach)
Sigma_m_list = [np.diag(m_unc_mat[k]**2) for k in range(len(coils))]

i_samples = []
shc_samples = []

for _ in range(Nmc):
    b_k = rng.multivariate_normal(b_new, b_new_cov)

    M_cols = []
    for k in range(len(coils)):
        m_k = rng.multivariate_normal(m_mat[k], Sigma_m_list[k])
        M_cols.append(m_k)
    M_k = np.column_stack(M_cols)  # (24, N)

    i_var = cp.Variable(len(coils))
    residual_k = cp.multiply(np.sqrt(weights), (M_k @ i_var + b_k))
    prob_k = cp.Problem(cp.Minimize(cp.sum_squares(residual_k)),
                        [i_var <= Imax_mA, i_var >= -Imax_mA])
    prob_k.solve(solver=cp.SCS, verbose=False)

    if i_var.value is None:
        continue

    i_k = np.asarray(i_var.value).ravel()
    s_k = M_k @ i_k + b_k
    i_samples.append(i_k)
    shc_samples.append(s_k)

i_samples = np.asarray(i_samples)
shc_samples = np.asarray(shc_samples)

sigma_current_mc = i_samples.std(axis=0, ddof=1) if len(i_samples) > 1 else np.full(len(coils), np.nan)
sigma_shc_mc = shc_samples.std(axis=0, ddof=1) if len(shc_samples) > 1 else np.full(24, np.nan)

# ============================================================
# Compute electrical settings for each coil 
# ============================================================

V_needed = []
R_needed = []
P_actual = []

for idx, coil in enumerate(coils):
    I_mA = optimized_currents[idx]
    I_sign = np.sign(I_mA) if I_mA != 0 else 1
    I_A = abs(I_mA) / 1000.0

    c = circ_map[str(coil)]
    Rmin, Rmax, Vmax = c["Rmin"], c["Rmax"], c["Vmax"]

    if I_A == 0:
        V_needed.append(0.0)
        R_needed.append(Rmax)
        P_actual.append(0.0)
        continue

    # choose largest allowable resistance without violating limits
    R_allowed = min(Rmax, Vmax / I_A, P_limit_W / (I_A**2))
    R_eff = max(Rmin, R_allowed)

    V_eff = I_A * R_eff
    P_eff = I_A * V_eff

    V_needed.append(V_eff * I_sign)
    R_needed.append(R_eff)
    P_actual.append(P_eff)

# ============================================================
# Save outputs
# ============================================================

df_predicted = pd.DataFrame({
    "Harmonic": harmonic_labels,
    "Baseline SHC": b_new,
    "Baseline Uncertainty": b_new_uncert,
    "Predicted SHC": predicted_SHCs,
    "Predicted Uncertainty": sigma_shc_mc,
})
predicted_file = os.path.join(output_path, "predicted_SHCs.csv")
df_predicted.to_csv(predicted_file, index=False)
print(f"Predicted SHCs saved to: {predicted_file}")

df_summary = pd.DataFrame({
    "Coil": coils.astype(str),
    "Optimized Current (mA)": optimized_currents,
    "Optimized Current Uncertainty (mA)": sigma_current_mc,
    "Voltage to drive current (V)": V_needed,
    "Resistance to drive current (Ohm)": R_needed,
    "Power (W)": P_actual
})
summary_file = os.path.join(output_path, "coil_summary.csv")
df_summary.to_csv(summary_file, index=False)
print(f"Coil summary saved to: {summary_file}")
