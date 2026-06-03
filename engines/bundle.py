"""
ACHE bundle design and rating solvers.

Design mode — given Q and temperatures, find the smallest bundle (n_bays) that
              satisfies both the heat-transfer area and tube-side turbulence.
Rating mode — given full geometry + flow conditions, find duty via NTU-ε.

Standard API 661 bay width 2438 mm (8 ft).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

from .air_properties import AirProps, air_properties, air_cp as _air_cp
from .fluid_properties import FluidProps
from .fin_geometry import FinGeometry, fin_geometry, overall_surface_efficiency
from .heat_transfer import (
    air_side_htc, tube_side_htc, overall_U,
    lmtd, f_factor_crossflow, ntu_crossflow, HTCBreakdown,
)

_BAY_WIDTH_M    = 2.438    # standard 8-ft bay width [m]
_RE_TURB        = 4000     # minimum Re for turbulent tube-side flow
_PASSES_ALLOWED = [1, 2, 3, 4, 6, 8, 12]
_MAX_BAYS       = 12       # hard upper bound on search


# ── Geometry dataclass ────────────────────────────────────────────────────────

@dataclass
class BundleGeometry:
    fin_type:    str
    n_rows:      int
    n_tubes_row: int    # per bay
    n_bays:      int
    L_tube_m:    float
    n_passes:    int
    fan_type:    str
    n_fans_bay:  int = 2

    @property
    def n_tubes_total(self) -> int:
        return self.n_bays * self.n_tubes_row * self.n_rows

    @property
    def n_tubes_per_pass(self) -> int:
        return max(1, self.n_tubes_total // self.n_passes)


@dataclass
class BundleDesignResult:
    geom:         BundleGeometry
    htc:          HTCBreakdown
    Q_kW:         float
    T_proc_in:    float
    T_proc_out:   float
    T_air_in:     float
    T_air_out:    float
    m_proc_kgs:   float
    m_air_kgs:    float
    G_air:        float
    v_tube_ms:    float
    Re_tube:      float
    A_total_m2:   float
    A_req_m2:     float
    area_margin:  float
    dP_air_Pa:    float
    P_fan_kW:     float
    n_passes_eff: int      # may be > user-requested if auto-adjusted
    warnings:     list[str] = field(default_factory=list)


@dataclass
class BundleRatingResult:
    geom:         BundleGeometry
    htc:          HTCBreakdown
    Q_kW:         float
    T_proc_in:    float
    T_proc_out:   float
    T_air_in:     float
    T_air_out:    float
    m_proc_kgs:   float
    m_air_kgs:    float
    G_air:        float
    v_tube_ms:    float
    Re_tube:      float
    A_total_m2:   float
    epsilon:      float
    dP_air_Pa:    float
    P_fan_kW:     float
    warnings:     list[str] = field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _tpr(fg: FinGeometry) -> int:
    """Tubes per row per bay (standard 2438 mm bay)."""
    return max(4, round(_BAY_WIDTH_M / fg.pitch_m))


def _free_flow_area(fg: FinGeometry, n_tubes_all: int, L: float) -> float:
    """Total minimum free-flow area for air [m²]."""
    return max(fg.pitch_m - fg.do_fin_m, 1e-4) * n_tubes_all * L


def _air_dp(G: float, air: AirProps, fg: FinGeometry, n_rows: int) -> float:
    Re = G * fg.do_m / air.mu
    f  = 0.508 * max(Re, 10.0)**(-0.521) * (fg.pitch_m / fg.do_m)**0.318
    return f * n_rows * G**2 / (2.0 * air.rho)


def _fan_kw(dP: float, m: float, rho: float, eta: float = 0.65) -> float:
    return dP * m / rho / (eta * 1000.0)


def _tube_rv(m_per_tube: float, f: FluidProps, Di: float):
    """Return (Re, v) for one tube."""
    Ac = math.pi * Di**2 / 4.0
    v  = m_per_tube / (f.rho * Ac)
    return f.rho * v * Di / f.mu, v


def _bays_max_turb(tpr: int, n_rows: int, n_passes: int,
                   m_proc: float, fluid: FluidProps, Di: float) -> int:
    """
    Maximum n_bays that keeps tube-side Re ≥ _RE_TURB.

    n_tp = n_bays × tpr × n_rows / n_passes
    Re   = m_proc / n_tp × Di / (A_c × μ) ≥ _RE_TURB
    → n_bays ≤ m_proc × n_passes × Di / (n_rows × tpr × A_c × μ × Re_min)
    """
    Ac  = math.pi * Di**2 / 4.0
    num = m_proc * n_passes * Di
    den = n_rows * tpr * Ac * fluid.mu * _RE_TURB
    return max(1, int(num / den))


# ── Design solver ─────────────────────────────────────────────────────────────

def design_bundle(
    Q_kW:         float,
    T_proc_in:    float,
    T_proc_out:   float,
    T_air_in:     float,
    T_air_out:    float,
    fluid_proc:   FluidProps,
    fin_type_key: str,
    n_rows:       int   = 6,
    L_tube_m:     float = 9.144,   # 30 ft
    n_passes:     int   = 2,
    fan_type:     str   = "Forced draft",
    altitude_m:   float = 0.0,
    Rf_air:       float = 1.85e-5,    # on total external area [m²K/W]
    Rf_tube:      float = 1.76e-4, # on inner area [m²K/W]
    k_wall:       float = 50.0,
) -> BundleDesignResult:
    """
    Design an ACHE bundle.

    Outer loop: try increasing n_passes until a feasible design is found.
    Inner loop: find the smallest n_bays (within the turbulent range) that
                provides enough heat transfer area.
    """
    Q_W      = Q_kW * 1e3
    fg       = fin_geometry(fin_type_key)
    warnings: list[str] = []

    dT_proc  = max(abs(T_proc_in - T_proc_out), 0.5)
    dT_air   = max(abs(T_air_out  - T_air_in),  0.5)
    m_proc   = Q_W / (fluid_proc.cp * dT_proc)
    m_air    = Q_W / (_air_cp(0.5 * (T_air_in + T_air_out)) * dT_air)

    LMTD_cf  = lmtd(T_proc_in, T_proc_out, T_air_in, T_air_out)
    F        = f_factor_crossflow(T_proc_in, T_proc_out, T_air_in, T_air_out)
    LMTD_eff = max(F * LMTD_cf, 0.5)

    air       = air_properties(0.5 * (T_air_in + T_air_out), altitude_m)
    tpr_val   = _tpr(fg)
    A_per_bay = tpr_val * n_rows * fg.A_total_pm * L_tube_m
    A_ff_bay  = _free_flow_area(fg, tpr_val, L_tube_m)

    # ── Outer loop: escalate n_passes until feasible ────────────────────────
    n_passes_eff = n_passes
    result_n_bays = _MAX_BAYS
    result_U = result_v = result_Re = result_h_bare = result_eta_f = result_h_eff = result_h_t = 0.0

    for pass_attempt in range(len(_PASSES_ALLOWED)):
        if n_passes_eff > _PASSES_ALLOWED[-1]:
            warnings.append("Could not achieve turbulent flow with any standard pass count.")
            n_passes_eff = _PASSES_ALLOWED[-1]
            break

        nb_max = min(_bays_max_turb(tpr_val, n_rows, n_passes_eff,
                                    m_proc, fluid_proc, fg.di_m),
                     _MAX_BAYS)

        # ── Inner loop: find smallest n_bays with enough area ───────────────
        found = False
        for nb in range(1, nb_max + 1):
            A_ff  = A_ff_bay * nb
            G     = m_air / A_ff
            hb, ef, he = air_side_htc(G, air, fg)

            n_tp    = max(1, tpr_val * nb * n_rows // n_passes_eff)
            mpt     = m_proc / n_tp
            Re, v   = _tube_rv(mpt, fluid_proc, fg.di_m)
            ht      = tube_side_htc(mpt, fluid_proc, fg.di_m)
            U       = overall_U(he, ht, fg, k_wall=k_wall, Rf_air=Rf_air, Rf_tube=Rf_tube)

            A_req   = Q_W / (U * LMTD_eff)

            if nb * A_per_bay >= A_req * 0.98:   # 2% tolerance
                result_n_bays = nb
                result_U, result_v, result_Re = U, v, Re
                result_h_bare, result_eta_f, result_h_eff, result_h_t = hb, ef, he, ht
                G_final = G
                A_req_final = A_req
                found = True
                break

        if found:
            if n_passes_eff != n_passes:
                warnings.append(
                    f"n_passes auto-adjusted from {n_passes} → {n_passes_eff} "
                    f"to maintain turbulent tube-side flow (Re ≥ {_RE_TURB})."
                )
            break

        # Escalate n_passes
        idx = next((i for i, p in enumerate(_PASSES_ALLOWED) if p > n_passes_eff),
                   len(_PASSES_ALLOWED) - 1)
        n_passes_eff = _PASSES_ALLOWED[idx]

    # ── Post-process ─────────────────────────────────────────────────────────
    n_bays  = result_n_bays
    A_total = n_bays * A_per_bay

    # Recompute final quantities with converged n_bays
    A_ff     = A_ff_bay * n_bays
    G_air    = m_air / A_ff
    h_bare, eta_f, h_eff = air_side_htc(G_air, air, fg)
    n_tp     = max(1, tpr_val * n_bays * n_rows // n_passes_eff)
    mpt      = m_proc / n_tp
    Re_tube, v_tube = _tube_rv(mpt, fluid_proc, fg.di_m)
    h_t      = tube_side_htc(mpt, fluid_proc, fg.di_m)
    U        = overall_U(h_eff, h_t, fg, k_wall=k_wall, Rf_air=Rf_air, Rf_tube=Rf_tube)
    A_req    = Q_W / (U * LMTD_eff)
    eta_o    = overall_surface_efficiency(eta_f, fg)

    if G_air < 2.0:
        warnings.append(f"Air mass flux G = {G_air:.1f} kg/(m²·s) — low; check fan sizing.")
    if G_air > 10.0:
        warnings.append(f"Air mass flux G = {G_air:.1f} kg/(m²·s) — high; check ΔP.")
    if v_tube < 0.3:
        warnings.append(f"Tube velocity {v_tube:.2f} m/s — risk of fouling/settling.")

    htc = HTCBreakdown(
        h_air_bare = h_bare, eta_fin = eta_f, eta_o = eta_o,
        h_air_eff  = h_eff,  h_tube  = h_t,  U     = U,
        LMTD = LMTD_cf, F = F, LMTD_eff = LMTD_eff,
    )

    dP_air = _air_dp(G_air, air, fg, n_rows)
    P_fan  = _fan_kw(dP_air, m_air, air.rho)

    geom = BundleGeometry(
        fin_type    = fin_type_key,
        n_rows      = n_rows,
        n_tubes_row = tpr_val,
        n_bays      = n_bays,
        L_tube_m    = L_tube_m,
        n_passes    = n_passes_eff,
        fan_type    = fan_type,
    )

    return BundleDesignResult(
        geom        = geom,
        htc         = htc,
        Q_kW        = Q_kW,
        T_proc_in   = T_proc_in,
        T_proc_out  = T_proc_out,
        T_air_in    = T_air_in,
        T_air_out   = T_air_out,
        m_proc_kgs  = m_proc,
        m_air_kgs   = m_air,
        G_air       = G_air,
        v_tube_ms   = v_tube,
        Re_tube     = Re_tube,
        A_total_m2  = A_total,
        A_req_m2    = A_req,
        area_margin = A_total / max(A_req, 1.0) - 1.0,
        dP_air_Pa   = dP_air,
        P_fan_kW    = P_fan,
        n_passes_eff = n_passes_eff,
        warnings    = warnings,
    )


# ── Rating solver ─────────────────────────────────────────────────────────────

def rate_bundle(
    geom:        BundleGeometry,
    T_proc_in:   float,
    m_proc_kgs:  float,
    fluid_proc:  FluidProps,
    T_air_in:    float,
    m_air_kgs:   float,
    altitude_m:  float = 0.0,
    Rf_air:      float = 1.85e-5,
    Rf_tube:     float = 1.76e-4,
    k_wall:      float = 50.0,
) -> BundleRatingResult:
    """Rate an existing bundle via NTU-ε method (cross-flow, both unmixed)."""
    fg       = fin_geometry(geom.fin_type)
    warnings: list[str] = []

    A_ff     = _free_flow_area(fg, geom.n_tubes_row * geom.n_bays, geom.L_tube_m)
    G_air    = m_air_kgs / max(A_ff, 1e-6)
    mpt      = m_proc_kgs / geom.n_tubes_per_pass
    Re_t, v  = _tube_rv(mpt, fluid_proc, fg.di_m)

    T_air_out = T_air_in + 10.0
    for _ in range(8):
        air = air_properties(0.5 * (T_air_in + T_air_out), altitude_m)

        hb, ef, he = air_side_htc(G_air, air, fg)
        ht  = tube_side_htc(mpt, fluid_proc, fg.di_m)
        U   = overall_U(he, ht, fg, k_wall=k_wall, Rf_air=Rf_air, Rf_tube=Rf_tube)

        A   = geom.n_tubes_total * fg.A_total_pm * geom.L_tube_m
        Cp  = m_proc_kgs * fluid_proc.cp
        Ca  = m_air_kgs  * _air_cp(air.T_C)
        Cmn = min(Cp, Ca)
        eps = ntu_crossflow(U * A / Cmn, Cmn / max(Cp, Ca))

        Q_W        = eps * Cmn * (T_proc_in - T_air_in)
        T_proc_out = T_proc_in  - Q_W / Cp
        T_air_out  = T_air_in   + Q_W / Ca

    LMTD_cf = lmtd(T_proc_in, T_proc_out, T_air_in, T_air_out)
    F        = f_factor_crossflow(T_proc_in, T_proc_out, T_air_in, T_air_out)
    eta_o    = overall_surface_efficiency(ef, fg)

    htc = HTCBreakdown(
        h_air_bare = hb, eta_fin = ef, eta_o = eta_o,
        h_air_eff  = he, h_tube  = ht, U     = U,
        LMTD = LMTD_cf, F = F, LMTD_eff = F * LMTD_cf,
    )

    dP = _air_dp(G_air, air, fg, geom.n_rows)
    Pf = _fan_kw(dP, m_air_kgs, air.rho)

    if v < 0.3:
        warnings.append(f"Tube velocity {v:.2f} m/s — low flow, may be laminar.")
    if T_proc_out > T_proc_in + 0.5:
        warnings.append("Process outlet T > inlet — check temperature inputs.")

    return BundleRatingResult(
        geom       = geom,
        htc        = htc,
        Q_kW       = Q_W / 1000.0,
        T_proc_in  = T_proc_in,
        T_proc_out = T_proc_out,
        T_air_in   = T_air_in,
        T_air_out  = T_air_out,
        m_proc_kgs = m_proc_kgs,
        m_air_kgs  = m_air_kgs,
        G_air      = G_air,
        v_tube_ms  = v,
        Re_tube    = Re_t,
        A_total_m2 = A,
        epsilon    = eps,
        dP_air_Pa  = dP,
        P_fan_kW   = Pf,
        warnings   = warnings,
    )


# ── Goal-seek ──────────────────────────────────────────────────────────────────

@dataclass
class GoalSeekRow:
    """One candidate design from the goal-seek sweep."""
    n_rows:       int
    n_passes_req: int   # passes requested (may be auto-raised)
    n_passes_eff: int   # effective passes used
    n_bays:       int
    U_Wm2K:       float
    G_air:        float
    v_tube_ms:    float
    Re_tube:      float
    A_total_m2:   float
    A_req_m2:     float
    area_margin:  float
    P_fan_kW:     float
    dP_air_Pa:    float
    score:        float   # lower = better
    recommended:  bool    = False
    warnings:     list[str] = field(default_factory=list)


def goal_seek_design(
    Q_kW:         float,
    T_proc_in:    float,
    T_proc_out:   float,
    T_air_in:     float,
    T_air_out:    float,
    fluid_proc:   FluidProps,
    fin_type_key: str,
    L_tube_m:     float  = 9.144,
    fan_type:     str    = "Forced draft",
    altitude_m:   float  = 0.0,
    Rf_air:       float  = 1.85e-5,
    Rf_tube:      float  = 1.76e-4,
    k_wall:       float  = 50.0,
) -> list[GoalSeekRow]:
    """
    Sweep (n_rows, n_passes) combinations and return every feasible design,
    sorted by fewest bays then best G_air (closest to 5 kg/m²s).

    Rows tried: 2, 3, 4, 6, 8.
    Passes tried: each value in _PASSES_ALLOWED up to 2 × n_rows.
    The design_bundle auto-escalates passes when the requested value gives
    laminar flow, so results include the effective pass count.

    Score = n_bays × 1000 + |G_air − 5|×10 + n_passes_eff   (lower = better)
    """
    rows_to_try  = [2, 3, 4, 6, 8]
    passes_to_try = _PASSES_ALLOWED   # [1,2,3,4,6,8,12]

    candidates: list[GoalSeekRow] = []
    seen_keys: set[tuple] = set()   # (n_bays, n_rows, n_passes_eff) — deduplicate

    for nr in rows_to_try:
        for np in passes_to_try:
            if np > nr * 3:          # skip impractical pass counts
                continue
            try:
                r = design_bundle(
                    Q_kW=Q_kW,
                    T_proc_in=T_proc_in, T_proc_out=T_proc_out,
                    T_air_in=T_air_in,   T_air_out=T_air_out,
                    fluid_proc=fluid_proc,
                    fin_type_key=fin_type_key,
                    n_rows=nr, L_tube_m=L_tube_m, n_passes=np,
                    fan_type=fan_type, altitude_m=altitude_m,
                    Rf_air=Rf_air, Rf_tube=Rf_tube, k_wall=k_wall,
                )
            except Exception:
                continue

            key = (r.geom.n_bays, nr, r.n_passes_eff)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            score = (r.geom.n_bays * 1000
                     + abs(r.G_air - 5.0) * 10
                     + r.n_passes_eff)

            candidates.append(GoalSeekRow(
                n_rows       = nr,
                n_passes_req = np,
                n_passes_eff = r.n_passes_eff,
                n_bays       = r.geom.n_bays,
                U_Wm2K       = r.htc.U,
                G_air        = r.G_air,
                v_tube_ms    = r.v_tube_ms,
                Re_tube      = r.Re_tube,
                A_total_m2   = r.A_total_m2,
                A_req_m2     = r.A_req_m2,
                area_margin  = r.area_margin,
                P_fan_kW     = r.P_fan_kW,
                dP_air_Pa    = r.dP_air_Pa,
                score        = score,
                warnings     = r.warnings,
            ))

    if not candidates:
        return []

    candidates.sort(key=lambda x: x.score)

    # Mark the single best row as recommended
    best = candidates[0]
    for c in candidates:
        c.recommended = (c is best)

    return candidates
