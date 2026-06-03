"""
AirHX validation against published literature data.

Run with:  python3 validate.py

References
----------
[1] Perry's Chemical Engineers' Handbook, 9th ed., Table 11-10 (ACHE U-values)
[2] GPSA Engineering Data Book, Sec. 10 (Air-Cooled Exchangers)
[3] Briggs & Young (1963), Chem. Eng. Prog. Symp. Ser. 59(41):1-10 (BY correlation)
[4] Incropera & DeWitt, "Fundamentals of Heat and Mass Transfer", 7th ed.
    Table 11.2 (overall heat transfer coefficients)
[5] Engineering Toolbox / industry practice — U on bare-tube area [W/m²K] or
    [BTU/h·ft²·°F].  Conversion: 1 BTU/(h·ft²·°F) = 5.678 W/(m²·K).
"""
import math, sys

from engines import (
    design_bundle, fluid_properties, fin_geometry,
    air_properties, air_side_htc,
)
from engines.heat_transfer import (
    tube_side_htc, lmtd, f_factor_crossflow,
    overall_U, ntu_crossflow,
)

PASS  = "\033[92mPASS\033[0m"
FAIL  = "\033[91mFAIL\033[0m"
WARN  = "\033[93mWARN\033[0m"

_BTU = 5.678   # W/m²K → BTU/(h·ft²·°F)

results = []

def check(name: str, value: float, lo: float, hi: float, unit: str = "") -> bool:
    ok = lo <= value <= hi
    tag = PASS if ok else FAIL
    pct = (value - (lo + hi) / 2) / ((hi - lo) / 2) * 100
    print(f"  [{tag}] {name}: {value:.3g} {unit}  (expected {lo:.3g}–{hi:.3g}, offset {pct:+.0f}%)")
    results.append(ok)
    return ok

def close(name: str, got: float, ref: float, tol_pct: float = 1.0) -> bool:
    dev = abs(got - ref) / abs(ref) * 100 if ref else 0
    ok  = dev <= tol_pct
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {name}: got {got:.4g}, ref {ref:.4g}, dev {dev:.2f}%  (tol ±{tol_pct}%)")
    results.append(ok)
    return ok


# ────────────────────────────────────────────────────────────────────────────
print("=" * 60)
print("TEST 1 — LMTD formula")
print("=" * 60)
# Counter-flow LMTD: hot 80→45, cold 35→55
# dT1 = 80-55=25, dT2 = 45-35=10, LMTD = (25-10)/ln(25/10)
dT1, dT2 = 25.0, 10.0
ref_lmtd = (dT1 - dT2) / math.log(dT1 / dT2)
close("LMTD counter-flow", lmtd(80, 45, 35, 55), ref_lmtd)

# When dT1=dT2, LMTD = that uniform dT. Here: dT1=80-55=25, dT2=60-35=25 → LMTD=25
close("LMTD uniform dT=25", lmtd(80, 60, 35, 55), 25.0, tol_pct=0.1)


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 2 — F-factor plausibility")
print("=" * 60)
# For pure counter-flow (same temps), F should approach 1.
# For the water-cooler case: P=(55-35)/(80-35)=0.444, R=(80-45)/(20)=1.75
# Published charts give F ≈ 0.74-0.76 for pure single-pass crossflow
F = f_factor_crossflow(80, 45, 35, 55)
check("F-factor crossflow [0.70–0.80]", F, 0.70, 0.80)

# Extreme approach (P→0): F→1
F_low_P = f_factor_crossflow(80, 79, 35, 36)
check("F-factor near-zero P [0.95–1.0]", F_low_P, 0.95, 1.0)


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 3 — Gnielinski tube-side HTC")
print("=" * 60)
# Reference: turbulent water at 60°C in 1\" tube
fluid60 = fluid_properties("Water", 60.0)
Di = 0.02118   # 1" tube ID [m]
# Manual calc at Re ≈ 7700 (mpt=0.06 kg/s)
mpt = 0.06
Ac  = math.pi * Di**2 / 4
v   = mpt / (fluid60.rho * Ac)
Re  = fluid60.rho * v * Di / fluid60.mu
f_d = (0.790 * math.log(Re) - 1.64)**-2
Nu  = (f_d / 8) * (Re - 1000) * fluid60.Pr / (
       1 + 12.7 * math.sqrt(f_d / 8) * (fluid60.Pr**(2/3) - 1))
h_ref = Nu * fluid60.k / Di
h_got = tube_side_htc(mpt, fluid60, Di)
close("tube-side HTC Re≈7700", h_got, h_ref, tol_pct=0.5)

# Laminar check: fully-developed laminar Nu = 4.36
mpt_lam = 0.003   # very low flow → laminar
h_lam = tube_side_htc(mpt_lam, fluid60, Di)
Re_lam = fluid60.rho * (mpt_lam / (fluid60.rho * Ac)) * Di / fluid60.mu
print(f"  Re (laminar case) = {Re_lam:.0f}")
h_lam_ref = 4.36 * fluid60.k / Di
close("tube-side HTC laminar Nu=4.36", h_lam, h_lam_ref, tol_pct=1.0)


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 4 — Briggs-Young air-side correlation")
print("=" * 60)
fg = fin_geometry('1"-L12-394')
air45 = air_properties(45.0, 0.0)

s = fg.fin_pitch_m - fg.fin_t_m
h = fg.fin_h_m
t = fg.fin_t_m

for G_test in [3.0, 5.0, 8.0]:
    Re_a    = G_test * fg.do_m / air45.mu
    Nu_ref  = (0.134 * Re_a**0.681 * air45.Pr**(1/3)
               * (s / h)**0.200 * (s / t)**0.1134)
    h_bare_ref = Nu_ref * air45.k / fg.do_m
    # air_side_htc returns (h_bare, eta_fin, h_eff); compare bare values directly
    h_bare_got, _, _ = air_side_htc(G_test, air45, fg)
    close(f"air-side h_bare at G={G_test:.0f} kg/m²s", h_bare_got, h_bare_ref, tol_pct=0.5)


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 5 — NTU-ε cross-flow formula")
print("=" * 60)
# NTU=2, C*=1, both unmixed: ε ≈ 0.614-0.618 (Incropera Fig 11.12)
# Formula: 1 - exp{(NTU^0.22/C*)×[exp(-C*×NTU^0.78)-1]} → 0.616
eps = ntu_crossflow(2.0, 1.0)
check("NTU=2, C*=1 → ε [0.60–0.63]", eps, 0.60, 0.63)
# At NTU→large, C*=0: ε → 1
eps_large = ntu_crossflow(20.0, 0.01)
check("NTU=20, C*≈0 → ε [0.98–1.00]", eps_large, 0.98, 1.00)


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 6 — Overall U: water cooler (literature range check)")
print("=" * 60)
# [1,2]: water cooling in forced-draft ACHE → U_bare = 100-130 BTU/(h·ft²·°F)
#       = 568-738 W/(m²K) on bare tube external area
# Our convention: U_total on total finned area; convert: U_bare = U × A_ratio
fluid_w = fluid_properties("Water", 62.5)
r = design_bundle(1000, 80, 45, 35, 55, fluid_w, '1"-L12-394', n_rows=6, n_passes=2)
A_ratio = fg.A_total_pm / fg.A_bare_pm
U_bare_w  = r.htc.U * A_ratio
U_btu_w   = U_bare_w / _BTU
check("U_bare water cooler [BTU/(h·ft²·°F)]", U_btu_w, 90.0, 150.0)

# [1]: light HC (diesel) → 50-90 BTU/(h·ft²·°F) on bare tube
# (lower than water: higher viscosity, lower thermal conductivity)
fluid_hc = fluid_properties("Diesel / Gas oil", 70.0)
r2 = design_bundle(500, 90, 50, 35, 55, fluid_hc, '1"-L12-394', n_rows=6, n_passes=2)
U_bare_hc = r2.htc.U * A_ratio
U_btu_hc  = U_bare_hc / _BTU
check("U_bare diesel cooler [BTU/(h·ft²·°F)]", U_btu_hc, 35.0, 110.0)

# Tube-side Re in turbulent zone
check("Water cooler Re_tube > 4000", r.Re_tube, 4001.0, 1e7)


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 7 — Design/rating round-trip consistency")
print("=" * 60)
# Rate the design geometry at design conditions → should recover ~Q within 15%
from engines import rate_bundle
geom = r.geom
rr = rate_bundle(geom, 80, r.m_proc_kgs, fluid_w, 35, r.m_air_kgs)
dev_Q = abs(rr.Q_kW - r.Q_kW) / r.Q_kW * 100
check("Rating Q vs design Q, deviation [0–15%]", dev_Q, 0.0, 15.0, unit="%")
check("Rating T_proc_out near 45°C [40–50]", rr.T_proc_out, 40.0, 50.0, unit="°C")


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 8 — Air properties (Sutherland + ISA)")
print("=" * 60)
air0  = air_properties(0.0, 0.0)    # air at 0°C, sea level
air15 = air_properties(15.0, 0.0)   # standard conditions

# ICAO / engineering tables
close("μ air at 0°C [Pa·s]",  air0.mu,  1.716e-5, tol_pct=0.5)
close("ρ air at 15°C [kg/m³]", air15.rho, 1.225,  tol_pct=0.5)
# ISA sea-level pressure 101325 Pa
close("P ISA sea level [Pa]", air0.P_Pa, 101325.0, tol_pct=0.1)


# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
n_pass = sum(results)
n_fail = len(results) - n_pass
print(f"TOTAL: {n_pass}/{len(results)} passed, {n_fail} failed")
if n_fail:
    print(f"\n{FAIL}S DETECTED — review items above.")
    sys.exit(1)
else:
    print(f"\nAll checks {PASS}.")
