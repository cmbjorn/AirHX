"""
Hybrid (evaporative) cooling for ACHEs.

Two modes:
  PRE_COOLER — Evaporative media or spray in front of the bundle
                lowers the effective air inlet temperature.
  DELUGE     — Water sprayed directly onto the finned tubes;
                evaporation provides latent cooling on top of the dry duty.

Water consumption is calculated from mass / energy balances and
psychrometric relationships.  No CoolProp required.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum

from .air_properties import (
    AirProps, air_properties, air_cp,
    saturation_pressure, humidity_ratio, wet_bulb_temperature,
    moist_air_enthalpy, isa_pressure,
)


class HybridMode(str, Enum):
    PRE_COOLER = "Pre-cooler (evaporative media)"
    DELUGE     = "Deluge (spray on bundle)"


@dataclass
class HybridResult:
    mode:            HybridMode
    T_air_in_dry:    float   # original dry-bulb air inlet [°C]
    T_air_in_eff:    float   # effective air inlet temperature after evaporative cooling [°C]
    T_wb:            float   # wet-bulb temperature of ambient air [°C]
    RH_in_pct:       float   # ambient RH [%]
    Q_extra_kW:      float   # additional duty delivered by evaporative effect [kW]
    m_water_kgs:     float   # water evaporation / consumption rate [kg/s]
    m_water_m3h:     float   # water consumption [m³/h]
    Q_duty_dry_kW:   float   # dry-only duty (reference) [kW]
    Q_duty_wet_kW:   float   # total duty with hybrid cooling [kW]
    T_proc_out_wet:  float   # expected process outlet temperature with hybrid [°C]
    notes:           list[str]


# ── Pre-cooler mode ───────────────────────────────────────────────────────────

def _pre_cooler_effective_T(
    T_dry:      float,
    T_wb:       float,
    approach_K: float = 4.0,
) -> float:
    """
    Effective air inlet temperature after an evaporative pre-cooler.
    The pre-cooler cools air toward wet-bulb with a given approach temperature.
    """
    T_eff = T_wb + approach_K
    return max(T_eff, T_dry - 25.0)   # can't be more than 25 K below dry-bulb


def pre_cooler_water_consumption(
    m_air_kgs:   float,
    T_dry_C:     float,
    T_eff_C:     float,
    RH_in_pct:   float,
    altitude_m:  float = 0.0,
) -> float:
    """
    Water evaporation rate [kg/s] for an evaporative pre-cooler.

    Based on the humidity change needed to saturate air from T_dry to T_eff:
      Δω = ω(T_eff, ~100%) − ω(T_dry, RH_in)
    """
    omega_in  = humidity_ratio(T_dry_C, RH_in_pct, altitude_m)
    omega_out = humidity_ratio(T_eff_C, min(98.0, RH_in_pct + 40.0), altitude_m)
    d_omega   = max(0.0, omega_out - omega_in)
    return m_air_kgs * d_omega


# ── Deluge mode ───────────────────────────────────────────────────────────────

_H_FG_MEAN = 2_430_000   # J/kg — latent heat at ~30 °C

def deluge_evaporation_rate(
    Q_extra_W: float,
) -> float:
    """Water evaporation rate [kg/s] to deliver Q_extra_W of additional duty."""
    return Q_extra_W / _H_FG_MEAN


def deluge_extra_duty(
    m_air_kgs:   float,
    T_air_in:    float,
    T_air_out:   float,
    RH_in_pct:   float,
    RH_out_pct:  float = 95.0,
    altitude_m:  float = 0.0,
) -> float:
    """
    Extra duty [W] from deluge evaporation on the air side.

    Estimated as the latent heat of water evaporated as air traverses the
    bundle from (T_air_in, RH_in) to (T_air_out, RH_out).
    """
    omega_in  = humidity_ratio(T_air_in,  RH_in_pct,  altitude_m)
    omega_out = humidity_ratio(T_air_out, RH_out_pct, altitude_m)
    d_omega   = max(0.0, omega_out - omega_in)
    return m_air_kgs * d_omega * _H_FG_MEAN


# ── Main interface ─────────────────────────────────────────────────────────────

def hybrid_cooling(
    mode:          HybridMode,
    m_air_kgs:     float,
    T_air_in:      float,
    T_air_out_dry: float,
    RH_in_pct:     float,
    Q_dry_kW:      float,
    T_proc_in:     float,
    T_proc_out_dry: float,
    fluid_cp:      float,        # process-side cp [J/kg·K]
    m_proc_kgs:    float,
    altitude_m:    float = 0.0,
    approach_K:    float = 4.0,  # pre-cooler approach to wet-bulb [K]
) -> HybridResult:
    """
    Calculate hybrid cooling performance and water consumption.

    For PRE_COOLER: lowers effective T_air_in, increases duty and cools process further.
    For DELUGE:     adds latent heat path on top of dry duty.
    """
    notes: list[str] = []
    T_wb = wet_bulb_temperature(T_air_in, RH_in_pct, altitude_m)

    if mode == HybridMode.PRE_COOLER:
        T_eff = _pre_cooler_effective_T(T_air_in, T_wb, approach_K)
        if T_eff >= T_air_in - 0.5:
            notes.append(
                "High RH — pre-cooler provides minimal benefit "
                f"(T_dry={T_air_in:.1f}°C, T_wb={T_wb:.1f}°C, approach={approach_K:.1f} K)."
            )

        # Extra duty: air enters cooler at T_eff instead of T_air_in
        # Q_extra ≈ m_air × cp_air × (T_air_in − T_eff)
        cp_air_mean = air_cp(0.5 * (T_air_in + T_eff))
        Q_extra_W   = m_air_kgs * cp_air_mean * (T_air_in - T_eff)
        Q_total_kW  = Q_dry_kW + Q_extra_W / 1000.0

        m_water = pre_cooler_water_consumption(
            m_air_kgs, T_air_in, T_eff, RH_in_pct, altitude_m
        )

        # New process outlet temperature
        T_proc_out_wet = T_proc_in - Q_total_kW * 1000.0 / (m_proc_kgs * fluid_cp)

    else:  # DELUGE
        T_eff = T_air_in   # air inlet unchanged
        # Approximate deluge effect: assume bundle can evaporate enough water to
        # raise air RH from RH_in to ~95% while maintaining same air outlet T
        Q_extra_W = deluge_extra_duty(
            m_air_kgs, T_air_in, T_air_out_dry, RH_in_pct,
            RH_out_pct=95.0, altitude_m=altitude_m,
        )
        Q_total_kW = Q_dry_kW + Q_extra_W / 1000.0
        m_water    = deluge_evaporation_rate(Q_extra_W)

        T_proc_out_wet = T_proc_in - Q_total_kW * 1000.0 / (m_proc_kgs * fluid_cp)

        if RH_in_pct > 85.0:
            notes.append(
                "Ambient RH > 85% — deluge evaporation severely limited; "
                "water benefit marginal."
            )

    if T_proc_out_wet < T_air_in + 2.0:
        notes.append(
            "Warning: process outlet temperature approaches air inlet — "
            "pinch constraint may limit achievable duty."
        )

    return HybridResult(
        mode            = mode,
        T_air_in_dry    = T_air_in,
        T_air_in_eff    = T_eff,
        T_wb            = T_wb,
        RH_in_pct       = RH_in_pct,
        Q_extra_kW      = Q_extra_W / 1000.0,
        m_water_kgs     = m_water,
        m_water_m3h     = m_water * 3600.0 / 1000.0,
        Q_duty_dry_kW   = Q_dry_kW,
        Q_duty_wet_kW   = Q_total_kW,
        T_proc_out_wet  = T_proc_out_wet,
        notes           = notes,
    )
