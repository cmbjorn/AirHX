"""
Circulation pump sizing for a closed cooling loop.

Calculates hydraulic duty, shaft power, and selects a standard motor size.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


# Standard motor ratings [kW]
_MOTOR_KW = [
    0.37, 0.55, 0.75, 1.1, 1.5, 2.2, 3.0, 4.0, 5.5, 7.5,
    11, 15, 18.5, 22, 30, 37, 45, 55, 75, 90, 110, 132, 160, 200, 250,
]


def _next_motor(P_kW: float) -> float:
    """Round up shaft power to the next standard motor size (kW)."""
    for m in _MOTOR_KW:
        if m >= P_kW:
            return m
    return P_kW   # oversized — return as-is


@dataclass
class PumpResult:
    Q_m3h:        float   # volumetric flow [m³/h]
    Q_ls:         float   # volumetric flow [L/s]
    H_m:          float   # total dynamic head [m]
    dP_total_kPa: float   # total pressure rise [kPa]
    P_shaft_kW:   float   # shaft power [kW]
    P_motor_kW:   float   # selected standard motor size [kW]
    NPSH_req_m:   float   # required NPSH (estimated) [m]
    eta_pump:     float   # assumed pump efficiency [-]
    notes:        list[str]


def size_pump(
    m_loop_kgs:    float,   # total loop mass flow [kg/s]
    rho:           float,   # fluid density [kg/m³]
    dP_ACHE_kPa:   float,   # pressure drop through ACHE tubes [kPa]
    dP_pipe_kPa:   float,   # pressure drop through main piping [kPa]
    dP_misc_kPa:   float = 0.0,   # fittings, valves, etc. [kPa]
    eta_pump:      float = 0.70,
    eta_motor:     float = 0.92,
    safety_margin: float = 1.10,  # head margin factor
) -> PumpResult:
    """
    Size a centrifugal circulation pump for a closed cooling loop.

    Pressure drops for ACHE, piping, and miscellaneous are summed;
    a 10% margin is applied before head and power calculations.
    """
    notes: list[str] = []

    dP_total_kPa = (dP_ACHE_kPa + dP_pipe_kPa + dP_misc_kPa) * safety_margin

    Q_m3s  = m_loop_kgs / rho
    Q_m3h  = Q_m3s * 3600.0
    Q_ls   = Q_m3s * 1000.0

    H_m    = dP_total_kPa * 1000.0 / (rho * 9.81)

    P_shaft_kW = rho * 9.81 * H_m * Q_m3s / (eta_pump * 1000.0)
    P_elec_kW  = P_shaft_kW / eta_motor
    P_motor_kW = _next_motor(P_elec_kW * 1.15)   # 15% service factor for motor

    # NPSH required: simplified Hydraulic Institute estimate
    NPSH_req_m = 0.5 + 0.002 * Q_ls**1.3   # rough estimate for centrifugal pump

    if eta_pump < 0.55:
        notes.append("Pump efficiency < 55% — consider larger impeller or different pump type.")
    if H_m > 150.0:
        notes.append("Head > 150 m — consider two pumps in series or higher-pressure class.")
    if Q_m3h > 500.0:
        notes.append("Flow > 500 m³/h — consider two pumps in parallel.")

    return PumpResult(
        Q_m3h        = Q_m3h,
        Q_ls         = Q_ls,
        H_m          = H_m,
        dP_total_kPa = dP_total_kPa,
        P_shaft_kW   = P_shaft_kW,
        P_motor_kW   = P_motor_kW,
        NPSH_req_m   = NPSH_req_m,
        eta_pump     = eta_pump,
        notes        = notes,
    )


def ache_tube_dp(
    m_proc_kgs:  float,
    fluid_rho:   float,
    fluid_mu:    float,
    Di_m:        float,
    L_tube_m:    float,
    n_passes:    int,
    n_tubes_row: int,
    n_rows:      int,
    n_bays:      int,
) -> float:
    """
    Estimate ACHE tube-side pressure drop [kPa] using Darcy-Weisbach.
    Includes nozzle entry/exit (2 velocity heads per pass) as minor losses.
    """
    n_per_pass = max(1, n_bays * n_tubes_row * n_rows // n_passes)
    m_per_tube = m_proc_kgs / n_per_pass
    A_t        = math.pi * Di_m**2 / 4.0
    v          = m_per_tube / (fluid_rho * A_t)
    Re         = fluid_rho * v * Di_m / fluid_mu

    # Darcy friction factor (Churchill 1977 explicit)
    if Re < 2300:
        f = 64.0 / max(Re, 1.0)
    else:
        rough = 0.046e-3   # drawn tubes, CS [m]
        A = (-2.457 * math.log((7.0 / Re)**0.9 + 0.27 * rough / Di_m))**16
        B = (37530.0 / Re)**16
        f = 8.0 * ((8.0 / Re)**12 + (A + B)**(-1.5))**(1.0/12.0)

    L_eff   = n_passes * L_tube_m   # equivalent length per stream
    dP_fric = f * (L_eff / Di_m) * fluid_rho * v**2 / 2.0
    dP_noz  = n_passes * 2.0 * fluid_rho * v**2 / 2.0  # entry + exit per pass

    return (dP_fric + dP_noz) / 1000.0   # Pa → kPa
