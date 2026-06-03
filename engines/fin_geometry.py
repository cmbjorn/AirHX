"""
Finned-tube geometry for air-cooled heat exchangers.

Covers standard API 661 extruded-aluminium fin configurations.
All dimensions in SI (metres) unless stated otherwise.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field


# ── Standard fin type catalogue ───────────────────────────────────────────────
# Key format: "<tube OD>-<fin height>-<fins/m>"
# All linear dimensions in mm here; converted to m in FinGeometry.

FIN_TYPES: dict[str, dict] = {
    '1"-L12-394': {
        "label":        '1" OD, 12.7 mm fin, 394 fins/m (10 fps) — API 661 std',
        "do_tube_mm":   25.40,
        "t_wall_mm":    2.11,        # min wall for carbon steel
        "fin_h_mm":     12.70,
        "fin_pitch_m":  1 / 394,     # m per fin
        "fin_t_mm":     0.40,
        "pitch_mm":     63.5,        # triangular tube pitch
        "k_fin":        204.0,       # W/(m·K) — aluminium
    },
    '1"-L16-276': {
        "label":        '1" OD, 15.9 mm fin, 276 fins/m (7 fps)',
        "do_tube_mm":   25.40,
        "t_wall_mm":    2.11,
        "fin_h_mm":     15.90,
        "fin_pitch_m":  1 / 276,
        "fin_t_mm":     0.40,
        "pitch_mm":     63.5,
        "k_fin":        204.0,
    },
    '1.5"-L12-394': {
        "label":        '1½" OD, 12.7 mm fin, 394 fins/m — API 661 std',
        "do_tube_mm":   38.10,
        "t_wall_mm":    2.77,
        "fin_h_mm":     12.70,
        "fin_pitch_m":  1 / 394,
        "fin_t_mm":     0.40,
        "pitch_mm":     95.25,
        "k_fin":        204.0,
    },
    '1.5"-L16-276': {
        "label":        '1½" OD, 15.9 mm fin, 276 fins/m',
        "do_tube_mm":   38.10,
        "t_wall_mm":    2.77,
        "fin_h_mm":     15.90,
        "fin_pitch_m":  1 / 276,
        "fin_t_mm":     0.40,
        "pitch_mm":     95.25,
        "k_fin":        204.0,
    },
    '1"-L12-433': {
        "label":        '1" OD, 12.7 mm fin, 433 fins/m (11 fps)',
        "do_tube_mm":   25.40,
        "t_wall_mm":    2.11,
        "fin_h_mm":     12.70,
        "fin_pitch_m":  1 / 433,
        "fin_t_mm":     0.35,
        "pitch_mm":     63.5,
        "k_fin":        204.0,
    },
    '2"-L12-394': {
        "label":        '2" OD, 12.7 mm fin, 394 fins/m',
        "do_tube_mm":   50.80,
        "t_wall_mm":    3.40,
        "fin_h_mm":     12.70,
        "fin_pitch_m":  1 / 394,
        "fin_t_mm":     0.40,
        "pitch_mm":     127.0,
        "k_fin":        204.0,
    },
}

FIN_TYPE_LABELS: dict[str, str] = {k: v["label"] for k, v in FIN_TYPES.items()}
FIN_TYPE_KEYS   = list(FIN_TYPES.keys())


@dataclass
class FinGeometry:
    """All derived geometry for a finned-tube bundle per unit tube length [m]."""
    fin_type:    str

    # Tube dimensions
    do_m:        float   # bare tube OD [m]
    di_m:        float   # bare tube ID [m]
    t_wall_m:    float   # tube wall thickness [m]

    # Fin dimensions
    fin_h_m:     float   # fin height [m]
    fin_t_m:     float   # fin thickness [m]
    fin_pitch_m: float   # fin-to-fin pitch [m]
    do_fin_m:    float   # finned OD (= do + 2·fin_h) [m]
    k_fin:       float   # fin thermal conductivity [W/(m·K)]

    # Tube layout
    pitch_m:     float   # tube centre-to-centre (triangular) [m]

    # Areas per metre of tube length [m²/m]
    A_bare_pm:   float   # bare tube external area [m²/m]
    A_fin_pm:    float   # total fin surface area [m²/m]
    A_total_pm:  float   # total external area (bare + fins) [m²/m]
    A_inner_pm:  float   # tube inner area [m²/m]

    # Ratios
    A_fin_frac:  float   # A_fin / A_total [-]
    A_r:         float   # A_total / A_inner (area ratio, external/internal) [-]


def fin_geometry(fin_type_key: str) -> FinGeometry:
    """Compute FinGeometry from a FIN_TYPES entry (per metre tube length)."""
    s = FIN_TYPES[fin_type_key]

    do    = s["do_tube_mm"]  * 1e-3
    t_w   = s["t_wall_mm"]   * 1e-3
    h_f   = s["fin_h_mm"]    * 1e-3
    t_f   = s["fin_t_mm"]    * 1e-3
    pitch = s["fin_pitch_m"]          # m per fin interval
    pt    = s["pitch_mm"]    * 1e-3
    k_f   = s["k_fin"]

    di       = do - 2.0 * t_w
    do_fin   = do + 2.0 * h_f
    n_fins_m = 1.0 / pitch            # fins per metre

    # Bare tube area between fins [m²/m]
    gap   = pitch - t_f               # free gap between fins
    A_bare = math.pi * do * gap * n_fins_m

    # Annular fin area (two faces + tip)
    r1 = do / 2.0
    r2 = do_fin / 2.0
    A_fin_face = 2.0 * math.pi * (r2**2 - r1**2)  # both faces, per fin
    A_fin_tip  = math.pi * do_fin * t_f             # tip, per fin
    A_fin      = (A_fin_face + A_fin_tip) * n_fins_m

    A_total    = A_bare + A_fin
    A_inner    = math.pi * di           # per metre

    return FinGeometry(
        fin_type    = fin_type_key,
        do_m        = do,
        di_m        = di,
        t_wall_m    = t_w,
        fin_h_m     = h_f,
        fin_t_m     = t_f,
        fin_pitch_m = pitch,
        do_fin_m    = do_fin,
        k_fin       = k_f,
        pitch_m     = pt,
        A_bare_pm   = A_bare,
        A_fin_pm    = A_fin,
        A_total_pm  = A_total,
        A_inner_pm  = A_inner,
        A_fin_frac  = A_fin / A_total,
        A_r         = A_total / A_inner,
    )


def fin_efficiency(h_air_bare: float, fg: FinGeometry) -> float:
    """
    Fin efficiency η_fin for an annular fin using the rectangular-profile approximation.

    h_air_bare : air-side HTC on bare-tube basis [W/m²K]
    Returns η_fin ∈ (0, 1].
    """
    r1 = fg.do_m / 2.0
    r2 = fg.do_fin_m / 2.0
    t  = fg.fin_t_m
    k  = fg.k_fin

    # Corrected fin half-height (includes fin tip; Schmidt approximation)
    h_corr = (r2 - r1) * (1.0 + 0.35 * math.log(r2 / r1))

    m = math.sqrt(2.0 * h_air_bare / (k * t))
    mh = m * h_corr
    if mh < 1e-9:
        return 1.0
    eta = math.tanh(mh) / mh
    return max(0.01, min(1.0, eta))


def overall_surface_efficiency(eta_fin: float, fg: FinGeometry) -> float:
    """Overall surface efficiency η_o = 1 − A_fin_frac·(1 − η_fin)."""
    return 1.0 - fg.A_fin_frac * (1.0 - eta_fin)
