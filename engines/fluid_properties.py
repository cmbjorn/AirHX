"""
Process-side and cooling-loop fluid property database.

Covers water, ethylene glycol / propylene glycol aqueous solutions, and
a handful of common hydrocarbon liquids used in process cooling service.
No heavy third-party packages required — pure tabulated data + linear interpolation.

All functions return SI units (Pa·s, W/m·K, J/kg·K, kg/m³).
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class FluidProps:
    name:  str
    T_C:   float   # mean temperature at which props were evaluated [°C]
    rho:   float   # density [kg/m³]
    cp:    float   # specific heat [J/(kg·K)]
    mu:    float   # dynamic viscosity [Pa·s]
    k:     float   # thermal conductivity [W/(m·K)]

    @property
    def Pr(self) -> float:
        return self.mu * self.cp / self.k


# ── Internal helpers ──────────────────────────────────────────────────────────

def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation; clamps to boundary values."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def _interp2(xs: list[float], ys: list[float],
             table: list[list[float]], x: float, y: float) -> float:
    """Bilinear interpolation. xs=outer axis, ys=inner axis."""
    x = max(xs[0], min(xs[-1], x))
    y = max(ys[0], min(ys[-1], y))
    ix = 0
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            ix = i; break
    tx = (x - xs[ix]) / (xs[ix + 1] - xs[ix]) if xs[ix + 1] != xs[ix] else 0.0
    v0 = _interp(ys, table[ix],     y)
    v1 = _interp(ys, table[ix + 1], y)
    return v0 + tx * (v1 - v0)


# ── Water ─────────────────────────────────────────────────────────────────────

_W_T   = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0, 120.0]   # °C
_W_RHO = [999.8, 998.2, 992.2, 983.2, 971.8, 958.4, 943.4]  # kg/m³
_W_CP  = [4218.,4182., 4179., 4184., 4196., 4216., 4250.]    # J/(kg·K)
_W_MU  = [1.793e-3,1.002e-3,0.653e-3,0.467e-3,0.355e-3,0.282e-3,0.232e-3]
_W_K   = [0.561, 0.598, 0.631, 0.651, 0.668, 0.680, 0.685]  # W/(m·K)


def _water_props(T_C: float) -> FluidProps:
    return FluidProps("Water", T_C,
        rho = _interp(_W_T, _W_RHO, T_C),
        cp  = _interp(_W_T, _W_CP,  T_C),
        mu  = _interp(_W_T, _W_MU,  T_C),
        k   = _interp(_W_T, _W_K,   T_C),
    )


# ── Ethylene glycol aqueous ───────────────────────────────────────────────────
# Outer axis: EG concentration wt%  [0, 30, 50]
# Inner axis: temperature °C        [0, 20, 40, 60, 80]

_EG_CONC = [0., 30., 50.]
_EG_T    = [0., 20., 40., 60., 80.]

_EG_RHO = [
    [999.8, 998.2, 992.2, 983.2, 971.8],   # 0%
    [1054., 1042., 1029., 1015., 999. ],    # 30%
    [1083., 1070., 1056., 1041., 1024.],    # 50%
]
_EG_CP = [
    [4218., 4182., 4179., 4184., 4196.],
    [3740., 3740., 3760., 3800., 3850.],
    [3480., 3490., 3520., 3560., 3610.],
]
_EG_MU = [
    [1.793e-3, 1.002e-3, 0.653e-3, 0.467e-3, 0.355e-3],
    [5.0e-3,   2.0e-3,   1.1e-3,   0.71e-3,  0.51e-3 ],
    [16.0e-3,  4.5e-3,   2.1e-3,   1.2e-3,   0.80e-3 ],
]
_EG_K = [
    [0.561, 0.598, 0.631, 0.651, 0.668],
    [0.490, 0.510, 0.525, 0.535, 0.542],
    [0.440, 0.457, 0.470, 0.480, 0.487],
]


def _eg_props(conc_pct: float, T_C: float, label: str) -> FluidProps:
    return FluidProps(label, T_C,
        rho = _interp2(_EG_CONC, _EG_T, _EG_RHO, conc_pct, T_C),
        cp  = _interp2(_EG_CONC, _EG_T, _EG_CP,  conc_pct, T_C),
        mu  = _interp2(_EG_CONC, _EG_T, _EG_MU,  conc_pct, T_C),
        k   = _interp2(_EG_CONC, _EG_T, _EG_K,   conc_pct, T_C),
    )


# ── Propylene glycol aqueous ──────────────────────────────────────────────────
# Representative data for PG 30% and PG 50%

_PG_CONC = [0., 30., 50.]
_PG_T    = [0., 20., 40., 60., 80.]

_PG_RHO = [
    [999.8, 998.2, 992.2, 983.2, 971.8],
    [1033., 1022., 1011., 998.,  984. ],
    [1057., 1046., 1034., 1021., 1007.],
]
_PG_CP = [
    [4218., 4182., 4179., 4184., 4196.],
    [3920., 3890., 3870., 3870., 3890.],
    [3680., 3660., 3650., 3650., 3670.],
]
_PG_MU = [
    [1.793e-3, 1.002e-3, 0.653e-3, 0.467e-3, 0.355e-3],
    [8.0e-3,   2.5e-3,   1.2e-3,   0.70e-3,  0.47e-3 ],
    [28.0e-3,  6.5e-3,   2.5e-3,   1.3e-3,   0.80e-3 ],
]
_PG_K = [
    [0.561, 0.598, 0.631, 0.651, 0.668],
    [0.470, 0.490, 0.505, 0.515, 0.522],
    [0.420, 0.435, 0.448, 0.458, 0.465],
]


def _pg_props(conc_pct: float, T_C: float, label: str) -> FluidProps:
    return FluidProps(label, T_C,
        rho = _interp2(_PG_CONC, _PG_T, _PG_RHO, conc_pct, T_C),
        cp  = _interp2(_PG_CONC, _PG_T, _PG_CP,  conc_pct, T_C),
        mu  = _interp2(_PG_CONC, _PG_T, _PG_MU,  conc_pct, T_C),
        k   = _interp2(_PG_CONC, _PG_T, _PG_K,   conc_pct, T_C),
    )


# ── Light hydrocarbon liquids ─────────────────────────────────────────────────
# Representative properties for common cooling-service process streams.

_HC_T = [20., 40., 60., 80., 100., 120.]  # °C

_HC_DATA: dict[str, dict[str, list[float]]] = {
    "Naphtha (light)": {
        "rho": [710., 695., 678., 662., 645., 627.],
        "cp":  [2180., 2230., 2280., 2340., 2400., 2460.],
        "mu":  [0.60e-3, 0.47e-3, 0.38e-3, 0.31e-3, 0.26e-3, 0.22e-3],
        "k":   [0.128, 0.123, 0.118, 0.113, 0.108, 0.103],
    },
    "Kerosene / Jet A": {
        "rho": [798., 783., 767., 750., 733., 715.],
        "cp":  [2050., 2100., 2150., 2210., 2270., 2330.],
        "mu":  [2.5e-3, 1.7e-3, 1.2e-3, 0.90e-3, 0.70e-3, 0.56e-3],
        "k":   [0.135, 0.130, 0.125, 0.119, 0.114, 0.108],
    },
    "Diesel / Gas oil": {
        "rho": [840., 825., 809., 793., 776., 758.],
        "cp":  [1950., 2000., 2060., 2120., 2180., 2250.],
        "mu":  [5.5e-3, 3.5e-3, 2.3e-3, 1.6e-3, 1.2e-3, 0.90e-3],
        "k":   [0.140, 0.135, 0.129, 0.123, 0.117, 0.111],
    },
    "Crude oil (medium)": {
        "rho": [870., 855., 839., 822., 805., 787.],
        "cp":  [1900., 1960., 2020., 2080., 2150., 2220.],
        "mu":  [20e-3, 10e-3, 5.5e-3, 3.2e-3, 2.0e-3, 1.4e-3],
        "k":   [0.143, 0.137, 0.131, 0.125, 0.119, 0.113],
    },
    "Amine (30% DEA)": {
        "rho": [1040., 1030., 1018., 1006., 993., 979.],
        "cp":  [3650., 3680., 3720., 3760., 3810., 3860.],
        "mu":  [4.5e-3, 2.8e-3, 1.8e-3, 1.2e-3, 0.85e-3, 0.62e-3],
        "k":   [0.480, 0.490, 0.498, 0.504, 0.508, 0.510],
    },
}


def _hc_props(name: str, T_C: float) -> FluidProps:
    d = _HC_DATA[name]
    return FluidProps(name, T_C,
        rho = _interp(_HC_T, d["rho"], T_C),
        cp  = _interp(_HC_T, d["cp"],  T_C),
        mu  = _interp(_HC_T, d["mu"],  T_C),
        k   = _interp(_HC_T, d["k"],   T_C),
    )


# ── Public API ────────────────────────────────────────────────────────────────

LOOP_FLUIDS = [
    "Water",
    "EG 30% (ethylene glycol)",
    "EG 50% (ethylene glycol)",
    "PG 30% (propylene glycol)",
    "PG 50% (propylene glycol)",
    "Naphtha (light)",
    "Kerosene / Jet A",
    "Diesel / Gas oil",
    "Crude oil (medium)",
    "Amine (30% DEA)",
    "Custom",
]


def fluid_properties(fluid_name: str, T_C: float,
                     custom: FluidProps | None = None) -> FluidProps:
    """
    Return FluidProps for *fluid_name* evaluated at mean temperature T_C [°C].
    Pass *custom* (a FluidProps) when fluid_name == 'Custom'.
    """
    if fluid_name == "Water":
        return _water_props(T_C)
    if fluid_name == "EG 30% (ethylene glycol)":
        return _eg_props(30.0, T_C, fluid_name)
    if fluid_name == "EG 50% (ethylene glycol)":
        return _eg_props(50.0, T_C, fluid_name)
    if fluid_name == "PG 30% (propylene glycol)":
        return _pg_props(30.0, T_C, fluid_name)
    if fluid_name == "PG 50% (propylene glycol)":
        return _pg_props(50.0, T_C, fluid_name)
    if fluid_name in _HC_DATA:
        return _hc_props(fluid_name, T_C)
    if fluid_name == "Custom" and custom is not None:
        return custom
    raise ValueError(f"Unknown fluid: {fluid_name!r}")
