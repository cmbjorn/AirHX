"""
Closed-loop expansion vessel sizing (diaphragm / bladder type).

Uses the standard acceptance-volume formula from EN 12828 / ASHRAE Handbook:
  V_vessel = V_exp / (1 − p0 / p_max)

where:
  V_exp    = V_system × β × ΔT  (volumetric thermal expansion)
  p0       = pre-charge pressure (absolute) ≈ static head pressure
  p_max    = maximum working pressure (absolute) = relief valve setting
  β        = mean volumetric thermal expansion coefficient of the fluid
"""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class ExpVesselResult:
    V_system_L:      float   # total system water volume [L]
    V_expansion_L:   float   # required expansion volume [L]
    V_vessel_L:      float   # total vessel volume (round up to next std size) [L]
    V_acceptance_L:  float   # acceptance volume of selected vessel [L]
    p_charge_bara:   float   # pre-charge (nitrogen) pressure [bara]
    p_max_bara:      float   # maximum working pressure [bara]
    T_cold_C:        float
    T_hot_C:         float
    notes:           list[str]


# Standard vessel sizes [L] (Reflex / Flamco / Zilmet range)
_STD_VESSEL_L = [
    8, 12, 18, 25, 35, 50, 80, 100, 150, 200, 250, 300, 400, 500,
    600, 750, 1000, 1500, 2000,
]


def _beta_water(T_C: float) -> float:
    """Approximate volumetric thermal expansion coefficient of water [1/K]."""
    # Fit to tabulated data 0–120 °C
    return 2.5e-5 * T_C + 1.5e-4   # ~1.5×10⁻⁴ at 0°C → ~4.5×10⁻³ at 120°C


def _beta_fluid(fluid_name: str, T_mean_C: float) -> float:
    """β [1/K] for common cooling fluids at mean temperature."""
    if "EG" in fluid_name or "PG" in fluid_name or "glycol" in fluid_name.lower():
        # Glycol solutions slightly higher than water
        conc = 30.0 if "30" in fluid_name else 50.0
        scale = 1.0 + conc * 0.008
        return _beta_water(T_mean_C) * scale
    return _beta_water(T_mean_C)


def size_expansion_vessel(
    V_system_L:   float,   # estimated total loop water volume [L]
    T_cold_C:     float,   # minimum loop temperature (filling/cold) [°C]
    T_hot_C:      float,   # maximum loop temperature (design) [°C]
    p_static_barg: float,  # static head pressure at vessel [barg]
    p_relief_barg: float,  # relief valve set pressure [barg]
    fluid_name:   str   = "Water",
    safety_factor: float = 1.1,
) -> ExpVesselResult:
    """
    Size a diaphragm expansion vessel for a closed cooling / heating loop.
    """
    notes: list[str] = []
    P_atm = 1.01325   # bara

    T_mean = 0.5 * (T_cold_C + T_hot_C)
    beta   = _beta_fluid(fluid_name, T_mean)
    dT     = T_hot_C - T_cold_C

    V_exp  = V_system_L * beta * dT * safety_factor

    # Pre-charge pressure = static head pressure (cold fill)
    p0     = p_static_barg + P_atm   # bara (absolute)
    p_max  = p_relief_barg + P_atm   # bara (absolute)

    if p0 >= p_max:
        notes.append(
            "Pre-charge pressure ≥ relief pressure — "
            "increase relief setting or reduce static head."
        )
        p0 = p_max * 0.9

    V_vessel = V_exp / (1.0 - p0 / p_max)

    # Round up to next standard size
    V_std = V_vessel
    for s in _STD_VESSEL_L:
        if s >= V_vessel:
            V_std = s
            break
    else:
        V_std = V_vessel   # beyond catalogue — use calculated

    # Acceptance volume of the selected vessel
    V_accept = V_std * (1.0 - p0 / p_max)

    if V_accept < V_exp:
        notes.append(
            f"Selected vessel acceptance volume ({V_accept:.0f} L) "
            f"< expansion volume ({V_exp:.0f} L) — size up."
        )

    if T_hot_C > 100.0:
        notes.append("System temperature > 100 °C — closed pressurised system required.")

    return ExpVesselResult(
        V_system_L     = V_system_L,
        V_expansion_L  = V_exp,
        V_vessel_L     = V_std,
        V_acceptance_L = V_accept,
        p_charge_bara  = p0,
        p_max_bara     = p_max,
        T_cold_C       = T_cold_C,
        T_hot_C        = T_hot_C,
        notes          = notes,
    )
