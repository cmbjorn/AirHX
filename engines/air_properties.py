"""
Dry-air thermodynamic properties and psychrometric helpers.

Valid range: -40 to 80 °C, 0 to 3000 m altitude, 0–100 % RH.
All SI units throughout.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


# ── Constants ─────────────────────────────────────────────────────────────────
_R_AIR   = 287.058   # J/(kg·K) — specific gas constant for dry air
_R_WATER = 461.5     # J/(kg·K) — specific gas constant for water vapour
_H_FG    = 2_501_000 # J/kg — latent heat of vaporisation at 0 °C (approx)
_CP_VAP  = 1_860     # J/(kg·K) — cp water vapour


@dataclass
class AirProps:
    T_C:     float   # dry-bulb temperature [°C]
    rho:     float   # density [kg/m³]
    mu:      float   # dynamic viscosity [Pa·s]
    k:       float   # thermal conductivity [W/(m·K)]
    cp:      float   # specific heat [J/(kg·K)]
    Pr:      float   # Prandtl number [-]
    P_Pa:    float   # static pressure [Pa]


# ── ISA pressure model ────────────────────────────────────────────────────────

def isa_pressure(altitude_m: float) -> float:
    """Atmospheric pressure [Pa] at altitude via ISA tropospheric model."""
    return 101_325.0 * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588


# ── Dry-air property functions ────────────────────────────────────────────────

def air_density(T_C: float, altitude_m: float = 0.0) -> float:
    """Dry-air density [kg/m³]."""
    return isa_pressure(altitude_m) / (_R_AIR * (T_C + 273.15))


def air_viscosity(T_C: float) -> float:
    """Dynamic viscosity [Pa·s] via Sutherland's law."""
    T_K = T_C + 273.15
    T0, mu0, C_S = 273.15, 1.716e-5, 110.4
    return mu0 * (T_K / T0) ** 1.5 * (T0 + C_S) / (T_K + C_S)


def air_conductivity(T_C: float) -> float:
    """Thermal conductivity [W/(m·K)]."""
    T_K = T_C + 273.15
    return 2.41e-2 * (T_K / 273.15) ** 0.82


def air_cp(T_C: float) -> float:
    """Specific heat at constant pressure [J/(kg·K)]."""
    return 1005.0 + 0.082 * T_C


def air_prandtl(T_C: float) -> float:
    return air_viscosity(T_C) * air_cp(T_C) / air_conductivity(T_C)


def air_properties(T_C: float, altitude_m: float = 0.0) -> AirProps:
    """Return all dry-air properties at T_C [°C] and altitude [m]."""
    P = isa_pressure(altitude_m)
    return AirProps(
        T_C  = T_C,
        rho  = P / (_R_AIR * (T_C + 273.15)),
        mu   = air_viscosity(T_C),
        k    = air_conductivity(T_C),
        cp   = air_cp(T_C),
        Pr   = air_prandtl(T_C),
        P_Pa = P,
    )


# ── Psychrometrics ─────────────────────────────────────────────────────────────

def saturation_pressure(T_C: float) -> float:
    """Saturation vapour pressure of water [Pa] (Buck equation, valid -40 to 80 °C)."""
    if T_C >= 0.0:
        return 611.21 * math.exp((18.678 - T_C / 234.5) * T_C / (257.14 + T_C))
    # ice surface
    return 611.15 * math.exp((23.036 - T_C / 333.7) * T_C / (279.82 + T_C))


def humidity_ratio(T_dry_C: float, RH_pct: float, altitude_m: float = 0.0) -> float:
    """Humidity ratio ω [kg_water / kg_dry_air]."""
    P      = isa_pressure(altitude_m)
    p_sat  = saturation_pressure(T_dry_C)
    p_v    = (RH_pct / 100.0) * p_sat
    return 0.621945 * p_v / (P - p_v)


def moist_air_enthalpy(T_dry_C: float, omega: float) -> float:
    """Specific enthalpy of moist air [J/kg_dry_air] at humidity ratio ω."""
    return air_cp(T_dry_C) * T_dry_C + omega * (_H_FG + _CP_VAP * T_dry_C)


def wet_bulb_temperature(T_dry_C: float, RH_pct: float,
                          altitude_m: float = 0.0) -> float:
    """Wet-bulb temperature [°C] via iterative psychrometric solution."""
    P  = isa_pressure(altitude_m)
    omega_in = humidity_ratio(T_dry_C, RH_pct, altitude_m)
    h_in     = moist_air_enthalpy(T_dry_C, omega_in)

    # Bracket: wet-bulb is between dew point and dry bulb; iterate with bisection
    T_lo, T_hi = T_dry_C - 50.0, T_dry_C

    def _residual(T_wb: float) -> float:
        p_sat_wb = saturation_pressure(T_wb)
        omega_wb = 0.621945 * p_sat_wb / (P - p_sat_wb)
        # Sprung psychrometric equation (ASHRAE)
        omega_adj = omega_wb - 6.6e-4 * (1 + 1.15e-3 * T_wb) * (T_dry_C - T_wb) * P / 101325
        return omega_adj - omega_in

    for _ in range(60):
        T_mid = 0.5 * (T_lo + T_hi)
        if _residual(T_mid) * _residual(T_lo) < 0:
            T_hi = T_mid
        else:
            T_lo = T_mid
        if (T_hi - T_lo) < 0.01:
            break

    return 0.5 * (T_lo + T_hi)
