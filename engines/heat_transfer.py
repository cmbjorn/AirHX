"""
Heat transfer correlations for air-cooled heat exchangers.

Air-side: Briggs-Young (1963) correlation for circular fins on staggered banks.
Tube-side: Gnielinski (turbulent) with laminar fallback.
LMTD and F-factor for pure cross-flow, both streams unmixed.
NTU-effectiveness for cross-flow.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

from .air_properties import AirProps
from .fluid_properties import FluidProps
from .fin_geometry import FinGeometry, fin_efficiency, overall_surface_efficiency


# ── Air-side ──────────────────────────────────────────────────────────────────

def air_side_htc(
    G_air: float,       # air mass flux through free-flow area [kg/(m²·s)]
    air:   AirProps,
    fg:    FinGeometry,
) -> tuple[float, float, float]:
    """
    Air-side heat transfer coefficient via Briggs-Young (1963).

    Returns (h_bare, eta_fin, h_eff) where:
      h_bare  — HTC referred to bare tube external area [W/(m²·K)]
      eta_fin — fin efficiency [-]
      h_eff   — effective HTC referred to total external area [W/(m²·K)]
    """
    # Characteristic length = bare tube OD
    Re = G_air * fg.do_m / air.mu

    # Briggs-Young: Nu = 0.134 Re^0.681 Pr^0.33 (s/h)^0.200 (s/t)^0.1134
    # s = fin pitch gap (fin-to-fin clear space), h = fin height, t = fin thickness
    s = fg.fin_pitch_m - fg.fin_t_m   # clear spacing between fins [m]
    h = fg.fin_h_m
    t = fg.fin_t_m

    # Guard against degenerate geometry
    s = max(s, 1e-4)
    h = max(h, 1e-4)
    t = max(t, 1e-5)

    Nu = (0.134 * Re**0.681 * air.Pr**(1/3)
          * (s / h)**0.200 * (s / t)**0.1134)
    h_bare = Nu * air.k / fg.do_m

    eta_f = fin_efficiency(h_bare, fg)
    eta_o = overall_surface_efficiency(eta_f, fg)
    # h_eff on total external area = h_bare × η_o
    # (Q = h_bare × [A_bare + η_fin·A_fin] × ΔT = h_bare·η_o·A_total·ΔT)
    h_eff = eta_o * h_bare

    return h_bare, eta_f, h_eff


# ── Tube-side ─────────────────────────────────────────────────────────────────

def tube_side_htc(
    m_tube:  float,       # mass flow per tube [kg/s]
    fluid:   FluidProps,
    Di_m:    float,       # tube inner diameter [m]
) -> float:
    """
    Tube-side HTC [W/(m²·K)] via Gnielinski correlation (turbulent)
    or constant Nu=4.36 (laminar).
    """
    A_cross = math.pi * Di_m**2 / 4.0
    v       = m_tube / (fluid.rho * A_cross)
    Re      = fluid.rho * v * Di_m / fluid.mu

    if Re < 1.0:
        return 10.0   # negligible flow

    Pr = fluid.Pr

    if Re < 2300:
        # Laminar, fully developed
        Nu = 4.36
    else:
        # Gnielinski (1976) — valid from Re ≈ 2300 upward (Re-1000 term handles transition)
        f  = (0.790 * math.log(Re) - 1.64) ** -2
        Nu = max(4.36, (f / 8.0) * (Re - 1000.0) * Pr / (
                        1.0 + 12.7 * math.sqrt(f / 8.0) * (Pr**(2/3) - 1.0)))

    return max(1.0, Nu * fluid.k / Di_m)


# ── Overall U ─────────────────────────────────────────────────────────────────

def overall_U(
    h_eff_air:   float,   # air-side HTC on total external area [W/(m²·K)]
    h_tube:      float,   # tube-side HTC on inner area [W/(m²·K)]
    fg:          FinGeometry,
    k_wall:      float = 50.0,    # tube wall conductivity [W/(m·K)] — CS
    Rf_air:      float = 1.85e-5, # air-side fouling on total external area [m²K/W]
    Rf_tube:     float = 1.76e-4, # tube-side fouling on inner area [m²K/W]
) -> float:
    """
    Overall U [W/(m²·K)] based on total external (finned) area.

    All resistances are referred to the total external area A_total:
      - Air side:   h_eff_air  already on total area
      - Wall:       r_wall = A_total × ln(do/di) / (2π k)    [m²K/W]
      - Tube side:  Rf_tube and 1/h_tube are on inner area
                    → multiply by A_r (= A_total/A_inner) to refer to total area

    Rf_air default: KLM spec 0.002 h·ft²·°F/Btu = 3.52×10⁻⁴ m²K/W on bare tube
    outer area → divided by typical A_total/A_bare ≈ 19 → 1.85×10⁻⁵ m²K/W on total area.
    API 661 uses 0.0002 h·ft²·°F/Btu (10× lower, cleaner service).

    Rf_tube default: 0.001 h·ft²·°F/Btu = 1.76×10⁻⁴ m²K/W on inner area (TEMA fouled).
    """
    Ar = fg.A_r   # A_total / A_inner

    # Wall conduction resistance referred to total external area [m²K/W]
    r_wall = fg.A_total_pm * math.log(fg.do_m / fg.di_m) / (2.0 * math.pi * k_wall)

    inv_U = (1.0 / h_eff_air
             + Rf_air
             + r_wall
             + (Rf_tube + 1.0 / h_tube) * Ar)
    return 1.0 / inv_U


# ── LMTD and F-factor ─────────────────────────────────────────────────────────

def lmtd(T_h_in: float, T_h_out: float, T_c_in: float, T_c_out: float) -> float:
    """
    Log-mean temperature difference [K] for counter-current baseline.
    Handles equal-end cases (returns the single terminal difference).
    """
    dT1 = T_h_in  - T_c_out
    dT2 = T_h_out - T_c_in
    if abs(dT1 - dT2) < 1e-6:
        return dT1 if dT1 > 0 else 1e-6
    if dT1 <= 0 or dT2 <= 0:
        return max(dT1, dT2, 1e-6)
    return (dT1 - dT2) / math.log(dT1 / dT2)


def f_factor_crossflow(T_h_in: float, T_h_out: float,
                        T_c_in: float, T_c_out: float) -> float:
    """
    LMTD correction factor F [-] for pure cross-flow, both streams unmixed.

    Analytical approximation from Bowman, Mueller & Nagle (1940).
    Returns F ∈ [0.5, 1.0]; clamps to 1.0 when P→0.
    """
    # Temperature effectiveness (shell-and-tube convention)
    if abs(T_h_in - T_c_in) < 1e-6:
        return 1.0
    P = (T_c_out - T_c_in) / (T_h_in - T_c_in)
    R = (T_h_in  - T_h_out) / (T_c_out - T_c_in) if abs(T_c_out - T_c_in) > 1e-6 else 1e6

    if P < 1e-6 or abs(R - 1.0) < 1e-4:
        return 1.0

    # Cross-flow approximation (Nusselt/Fischer)
    # Valid for typical ACHE range (P < 0.9, R < 8)
    try:
        if abs(R - 1.0) < 0.01:
            F = (P - 1.0) / (math.log(1.0 - P) * P)
        else:
            sqrt_R2 = math.sqrt(R**2 + 1.0)
            num  = sqrt_R2 * math.log((1.0 - P) / (1.0 - P * R))
            denom = (R - 1.0) * math.log(
                        (2.0 - P * (R + 1.0 - sqrt_R2)) /
                        (2.0 - P * (R + 1.0 + sqrt_R2)))
            F = num / denom
    except (ValueError, ZeroDivisionError):
        F = 0.75   # conservative default

    return max(0.50, min(1.0, F))


# ── NTU–effectiveness ─────────────────────────────────────────────────────────

def ntu_crossflow(NTU: float, C_ratio: float) -> float:
    """
    Thermal effectiveness ε for cross-flow, both fluids unmixed.

    ε = 1 − exp{ (1/Cr) · NTU^0.22 · [exp(−Cr·NTU^0.78) − 1] }
    (Incropera & DeWitt, widely used approximation)
    """
    if NTU < 1e-9:
        return 0.0
    Cr = max(C_ratio, 1e-6)
    return 1.0 - math.exp(
        (NTU**0.22 / Cr) * (math.exp(-Cr * NTU**0.78) - 1.0)
    )


@dataclass
class HTCBreakdown:
    """Heat transfer coefficient summary for one operating point."""
    h_air_bare:  float   # air-side, bare tube basis [W/m²K]
    eta_fin:     float   # fin efficiency [-]
    eta_o:       float   # overall surface efficiency [-]
    h_air_eff:   float   # air-side effective, total area basis [W/m²K]
    h_tube:      float   # tube-side [W/m²K]
    U:           float   # overall [W/m²K], total external area basis
    LMTD:        float   # counter-flow LMTD [K]
    F:           float   # LMTD correction factor [-]
    LMTD_eff:    float   # F × LMTD [K]
