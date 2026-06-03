"""
Main cooling loop pipe sizing.

Selects the smallest DN that keeps flow velocity ≤ v_max,
then reports velocity, Reynolds number, friction factor, and ΔP/100 m.

Two material options: carbon steel (sch 40) and stainless steel (sch 10S).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field


# ── Pipe dimension tables ──────────────────────────────────────────────────────
# (DN, OD_mm, wall_CS_mm, wall_SS_mm)  — ASME B36.10 / B36.19

_PIPE_DIMS: list[tuple[int, float, float, float]] = [
    (25,   33.40, 3.38, 1.65),
    (32,   42.16, 3.56, 1.65),
    (40,   48.26, 3.68, 1.65),
    (50,   60.33, 3.91, 1.65),
    (65,   73.03, 5.16, 2.11),
    (80,   88.90, 5.49, 2.11),
    (100, 114.30, 6.02, 2.77),
    (125, 141.30, 6.55, 2.77),
    (150, 168.28, 7.11, 2.77),
    (200, 219.08, 8.18, 3.76),
    (250, 273.05, 9.27, 4.19),
    (300, 323.85, 9.53, 4.57),
    (350, 355.60,11.13, 4.78),
    (400, 406.40,12.70, 4.78),
    (450, 457.20,12.70, 4.78),
    (500, 508.00,12.70, 4.78),
    (600, 609.60,12.70, 4.78),
]

DN_LIST = [d[0] for d in _PIPE_DIMS]


def _pipe_id(OD_mm: float, t_mm: float) -> float:
    """Inner diameter [mm]."""
    return OD_mm - 2.0 * t_mm


# ── Friction factor (Churchill 1977) ─────────────────────────────────────────

def _darcy_f(Re: float, Di_m: float, roughness_m: float) -> float:
    """Darcy-Weisbach friction factor via Churchill (1977) explicit formula."""
    if Re < 1.0:
        return 64.0
    if Re < 2300:
        return 64.0 / Re
    eps_r = roughness_m / Di_m
    A = (-2.457 * math.log((7.0 / Re)**0.9 + 0.27 * eps_r))**16
    B = (37530.0 / Re)**16
    return 8.0 * ((8.0 / Re)**12 + (A + B)**(-1.5))**(1.0 / 12.0)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class PipeSizeResult:
    DN:          int     # nominal diameter [mm]
    OD_mm:       float
    t_wall_mm:   float
    Di_mm:       float
    v_ms:        float   # actual mean velocity [m/s]
    Re:          float
    f_darcy:     float
    dP_100m_kPa: float   # pressure drop per 100 m of straight pipe [kPa]
    material:    str
    notes:       list[str] = field(default_factory=list)


# ── Sizing function ───────────────────────────────────────────────────────────

def size_pipe(
    m_kgs:      float,       # mass flow rate [kg/s]
    rho:        float,       # fluid density [kg/m³]
    mu:         float,       # dynamic viscosity [Pa·s]
    v_max:      float = 2.5, # maximum allowable velocity [m/s]
    v_target:   float = 1.5, # preferred design velocity [m/s]
    material:   str   = "Carbon steel",
    roughness_m: float = 4.6e-5,   # 0.046 mm — commercial steel
) -> PipeSizeResult:
    """
    Select smallest pipe DN where velocity ≤ v_max.
    Returns PipeSizeResult with hydraulic data.
    """
    notes: list[str] = []
    Q_m3s = m_kgs / rho

    use_ss = "stainless" in material.lower() or "SS" in material
    if use_ss:
        roughness_m = 1.5e-5   # 0.015 mm — electropolished SS approx

    selected = None
    for DN, OD_mm, t_cs, t_ss in _PIPE_DIMS:
        t_w  = t_ss if use_ss else t_cs
        Di_m = (OD_mm - 2.0 * t_w) / 1000.0
        A    = math.pi * Di_m**2 / 4.0
        v    = Q_m3s / A
        if v <= v_max:
            selected = (DN, OD_mm, t_w, Di_m, v)
            break

    if selected is None:
        # Use largest available
        DN, OD_mm, t_cs, t_ss = _PIPE_DIMS[-1]
        t_w  = t_ss if use_ss else t_cs
        Di_m = (OD_mm - 2.0 * t_w) / 1000.0
        A    = math.pi * Di_m**2 / 4.0
        v    = Q_m3s / A
        selected = (DN, OD_mm, t_w, Di_m, v)
        notes.append(
            f"Flow exceeds DN600 capacity at v_max={v_max:.1f} m/s — "
            f"consider parallel lines or larger custom pipe."
        )

    DN, OD_mm, t_w, Di_m, v = selected
    Re   = rho * v * Di_m / mu
    f    = _darcy_f(Re, Di_m, roughness_m)
    dP   = f * (100.0 / Di_m) * rho * v**2 / 2.0 / 1000.0   # kPa per 100 m

    if v < 0.3:
        notes.append("Velocity < 0.3 m/s — risk of sedimentation in horizontal runs.")
    if v > 2.0:
        notes.append("Velocity > 2.0 m/s — check noise and erosion at fittings.")
    if Re < 4000:
        notes.append("Laminar/transitional flow — heat transfer and ΔP estimates less accurate.")

    return PipeSizeResult(
        DN          = DN,
        OD_mm       = OD_mm,
        t_wall_mm   = t_w,
        Di_mm       = Di_m * 1000.0,
        v_ms        = v,
        Re          = Re,
        f_darcy     = f,
        dP_100m_kPa = dP,
        material    = material,
        notes       = notes,
    )


def pipe_loop_dp(
    pipe_result: PipeSizeResult,
    L_total_m:  float,
    n_elbows_90: int = 10,
    n_tees:      int = 4,
    n_valves_gate: int = 4,
) -> float:
    """
    Estimate total loop pipe pressure drop [kPa] including fittings.
    Uses equivalent-length method.
    """
    Di = pipe_result.Di_mm / 1000.0

    # Equivalent lengths [× Di]
    L_eq_elbow = 30.0
    L_eq_tee   = 60.0
    L_eq_valve = 8.0

    L_eq = (n_elbows_90 * L_eq_elbow
            + n_tees     * L_eq_tee
            + n_valves_gate * L_eq_valve) * Di

    L_eff = L_total_m + L_eq
    return pipe_result.dP_100m_kPa * L_eff / 100.0
