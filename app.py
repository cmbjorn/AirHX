"""
AirHX — Air-Cooled Heat Exchanger (ACHE / Fin-Fan) Design & Rating Tool

Screening-level tool for process engineers.
Not a certified design tool — for inquiry and FEED scoping only.
"""
import math
import streamlit as st
import plotly.graph_objects as go

import pandas as pd

from engines import (
    fluid_properties, LOOP_FLUIDS, FluidProps,
    fin_geometry, FIN_TYPE_KEYS, FIN_TYPE_LABELS,
    design_bundle, rate_bundle, BundleGeometry,
    BundleDesignResult, BundleRatingResult,
    air_properties,
    HybridMode, hybrid_cooling,
    size_pump, ache_tube_dp, pipe_loop_dp,
    size_expansion_vessel,
    size_pipe, pipe_loop_dp as _pipe_dp,
    GoalSeekRow, goal_seek_design,
)

st.set_page_config(
    page_title="AirHX",
    page_icon="💨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Colour constants ───────────────────────────────────────────────────────────
_BLUE  = "#1e3a5f"
_AMBER = "#92400e"
_GREEN = "#166534"

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"<h2 style='color:{_BLUE};margin-bottom:4px'>AirHX</h2>", unsafe_allow_html=True)
    st.caption("Air-cooled heat exchanger — design & rating")

    # ── Report buttons ──────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    gen_html = c1.button("Datasheet", use_container_width=True)
    gen_docx = c2.button("Report", use_container_width=True)

    if "report_html" in st.session_state:
        st.download_button(
            "📥 Datasheet (HTML→PDF)",
            data=st.session_state["report_html"],
            file_name=st.session_state.get("report_fname", "airhx_datasheet.html"),
            mime="text/html",
            use_container_width=True,
        )
    if "report_docx" in st.session_state:
        st.download_button(
            "📥 Report (.docx)",
            data=st.session_state["report_docx"],
            file_name=st.session_state.get("report_docx_fname", "airhx_report.docx"),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    st.divider()

    # ── Project ─────────────────────────────────────────────────────────────
    proj_name  = st.text_input("Project",    value="New Project",  key="proj_name")
    tag        = st.text_input("Tag / unit", value="ACHE-100",     key="tag")
    issued_for = st.selectbox("Issued for",
                              ["Enquiry", "FEED", "Detail", "As-built"], key="issued_for")

    st.divider()

    # ── Mode ────────────────────────────────────────────────────────────────
    mode = st.radio("Calculation mode", ["Design", "Rating"], horizontal=True, key="mode")

    st.divider()

    # ── Process conditions ──────────────────────────────────────────────────
    st.subheader("Process")
    fluid_name = st.selectbox("Tube-side fluid", LOOP_FLUIDS, key="fluid_name")

    custom_fluid = None
    if fluid_name == "Custom":
        with st.expander("Custom fluid properties"):
            c_rho = st.number_input("Density [kg/m³]",      value=850.0, step=10.0)
            c_cp  = st.number_input("Specific heat [J/kg·K]", value=2100.0, step=50.0)
            c_mu  = st.number_input("Viscosity [mPa·s]",     value=2.0, step=0.1)
            c_k   = st.number_input("Conductivity [W/m·K]",  value=0.13, step=0.01)
            custom_fluid = FluidProps("Custom", 60.0, c_rho, c_cp, c_mu*1e-3, c_k)

    T_proc_in  = st.number_input("Process inlet T [°C]",  value=80.0, step=1.0, key="T_proc_in")
    T_proc_out = st.number_input("Process outlet T [°C]", value=45.0, step=1.0, key="T_proc_out")

    if mode == "Design":
        Q_kW = st.number_input("Duty Q [kW]", value=1000.0, min_value=1.0, step=50.0, key="Q_kW")
    else:
        m_proc_kgs = st.number_input("Process mass flow [kg/s]", value=6.83, min_value=0.01,
                                     step=0.1, key="m_proc_kgs")

    st.divider()

    # ── Air conditions ──────────────────────────────────────────────────────
    st.subheader("Air")
    T_air_in   = st.number_input("Air inlet (ambient) T [°C]", value=35.0, step=1.0, key="T_air_in")
    altitude_m = st.number_input("Site altitude [m asl]", value=0.0, step=100.0, key="altitude_m")

    if mode == "Design":
        T_air_out = st.number_input("Air outlet T [°C]", value=55.0, step=1.0, key="T_air_out_d")
    else:
        m_air_kgs = st.number_input("Total air mass flow [kg/s]", value=50.0, min_value=1.0,
                                    step=1.0, key="m_air_kgs")

    st.divider()

    # ── Bundle geometry ─────────────────────────────────────────────────────
    st.subheader("Bundle geometry")
    fin_key  = st.selectbox("Fin type", FIN_TYPE_KEYS,
                             format_func=lambda k: FIN_TYPE_LABELS[k], key="fin_key")

    # V-type note: same B-Y correlations; not suited where recirculation is a problem
    _FAN_TYPES = ["Forced draft", "Induced draft", "V-type / A-frame (forced draft)"]
    fan_type = st.selectbox("Fan arrangement", _FAN_TYPES, key="fan_type")
    if "V-type" in fan_type:
        st.caption(
            "V-type uses identical Briggs-Young correlations. "
            "Not recommended where hot-air recirculation is a concern (KLM / literature consensus)."
        )

    # Bay width — standard options per API 661 / common practice
    _BAY_WIDTHS = {
        "2.438 m  (8 ft) — standard": 2.438,
        "3.048 m (10 ft)":             3.048,
        "3.658 m (12 ft) — wide":      3.658,
    }
    bay_w_sel  = st.selectbox("Bay width", list(_BAY_WIDTHS.keys()),
                               key="bay_w_sel")
    bay_width_m = _BAY_WIDTHS[bay_w_sel]

    c1, c2 = st.columns(2)
    n_rows   = c1.number_input("Rows",   value=6, min_value=1, max_value=12, step=1, key="n_rows")
    n_passes = c2.number_input("Passes", value=2, min_value=1, max_value=12, step=1, key="n_passes")

    # Standard tube lengths per KLM spec + API 661 common practice
    _STD_LENGTHS = {
        "2.44 m  (8 ft)":  2.438,
        "3.05 m (10 ft)":  3.048,
        "4.57 m (15 ft)":  4.572,
        "6.07 m (20 ft)":  6.096,
        "7.31 m (24 ft)":  7.315,
        "9.14 m (30 ft)":  9.144,
        "10.36 m (34 ft)": 10.363,
        "12.19 m (40 ft)": 12.192,
    }
    _default_len = "9.14 m (30 ft)"
    L_sel    = st.selectbox("Tube length", list(_STD_LENGTHS.keys()),
                             index=list(_STD_LENGTHS.keys()).index(_default_len),
                             key="L_tube_sel")
    L_tube_m = _STD_LENGTHS[L_sel]

    if mode == "Rating":
        n_bays_r  = st.number_input("Number of bays", value=1, min_value=1, max_value=20, step=1, key="n_bays_r")
        n_tubes_r = st.number_input("Tubes per row (per bay)", value=38, min_value=4, step=1, key="n_tubes_r")

    # Recirculation correction (KLM: +1–2°C near buildings, +8°C near engines)
    with st.expander("Hot-air recirculation correction"):
        recirc_dT = st.number_input(
            "Add to air inlet T [°C]",
            value=0.0, min_value=0.0, max_value=15.0, step=0.5,
            help="KLM spec: add 1–2°C for locations near large buildings; "
                 "up to 8°C near engine exhausts. Added to T_air_in before calculation.",
            key="recirc_dT",
        )

    with st.expander("Fouling & wall"):
        st.caption("Rf_air on total external (finned) area; Rf_tube on inner area.")
        # KLM spec: air-side 0.002 h·ft²·°F/Btu = 3.52e-4 m²K/W on bare tube ÷ ~19 = 1.85e-5 on total area
        # API 661:  air-side 0.0002 h·ft²·°F/Btu → 1.85e-6 on total area  (cleaner service)
        Rf_air_x  = st.number_input("Air-side Rf [×10⁻⁵ m²K/W, total area]",
                                     value=1.85, step=0.1,
                                     help="KLM 1.85; API 661 clean 0.19; dirty 3.5")
        Rf_air    = Rf_air_x * 1e-5
        Rf_tube   = st.number_input("Tube-side Rf [×10⁻⁴ m²K/W, inner area]",
                                     value=1.76, step=0.1,
                                     help="TEMA: 1.76 = 0.001 h·ft²·°F/Btu") * 1e-4
        k_wall    = st.number_input("Wall conductivity [W/m·K]", value=50.0, step=5.0)

    if mode == "Design":
        run_gs = st.button("🔍 Goal Seek", use_container_width=True,
                           help="Sweep row/pass combinations and rank feasible designs.")

    st.divider()

    # ── Hybrid cooling ──────────────────────────────────────────────────────
    hybrid_on = st.checkbox("Hybrid (evaporative) cooling", key="hybrid_on")
    if hybrid_on:
        with st.expander("Hybrid settings", expanded=True):
            hybrid_mode_str = st.radio("Mode",
                                       [HybridMode.PRE_COOLER.value, HybridMode.DELUGE.value],
                                       key="hybrid_mode")
            RH_in   = st.slider("Ambient RH [%]", 10, 100, 40, key="RH_in")
            approach_K = st.number_input("Wet-bulb approach [K]", value=4.0, min_value=1.0,
                                          step=0.5, key="approach_K")

    st.divider()

    # ── Cooling loop sizing ─────────────────────────────────────────────────
    loop_on = st.checkbox("Size cooling loop (pump, vessel, pipes)", key="loop_on")
    if loop_on:
        with st.expander("Loop settings", expanded=True):
            V_sys   = st.number_input("System water volume [L]", value=500.0, step=50.0, key="V_sys")
            T_cold  = st.number_input("Cold fill temperature [°C]", value=10.0, step=5.0, key="T_cold")
            p_stat  = st.number_input("Static head at vessel [barg]", value=0.5, step=0.1, key="p_stat")
            p_rel   = st.number_input("Relief valve setting [barg]", value=3.0, step=0.5, key="p_rel")
            L_pipe  = st.number_input("Main pipe loop length [m]", value=100.0, step=10.0, key="L_pipe")
            pipe_mat = st.selectbox("Pipe material", ["Carbon steel", "Stainless steel"],
                                     key="pipe_mat")
            v_tgt   = st.number_input("Target pipe velocity [m/s]", value=1.5, step=0.1, key="v_tgt")


# ── Compute ───────────────────────────────────────────────────────────────────
T_proc_mean = 0.5 * (T_proc_in + T_proc_out)
fluid = fluid_properties(fluid_name, T_proc_mean, custom_fluid)

# Apply recirculation correction to air inlet temperature
T_air_in_eff = T_air_in + recirc_dT

# Goal-seek: run sweep when button pressed, cache in session_state
if mode == "Design" and run_gs:
    T_air_out_gs = st.session_state.get("T_air_out_d", 55.0)
    try:
        gs_rows = goal_seek_design(
            Q_kW=Q_kW,
            T_proc_in=T_proc_in, T_proc_out=T_proc_out,
            T_air_in=T_air_in_eff, T_air_out=T_air_out_gs,
            fluid_proc=fluid,
            fin_type_key=fin_key,
            L_tube_m=L_tube_m,
            fan_type=fan_type,
            altitude_m=altitude_m,
            Rf_air=Rf_air, Rf_tube=Rf_tube, k_wall=k_wall,
            bay_width_m=bay_width_m,
        )
        st.session_state["gs_rows"] = gs_rows
    except Exception as exc:
        st.session_state["gs_rows"] = []
        st.session_state["gs_error"] = str(exc)

result: BundleDesignResult | BundleRatingResult | None = None
errors: list[str] = []

try:
    if mode == "Design":
        T_air_out = st.session_state.get("T_air_out_d", 55.0)
        if T_air_out <= T_air_in_eff:
            errors.append("Air outlet temperature must be > effective air inlet temperature.")
        elif T_proc_out >= T_proc_in:
            errors.append("Process outlet temperature must be < inlet temperature.")
        else:
            result = design_bundle(
                Q_kW=Q_kW,
                T_proc_in=T_proc_in, T_proc_out=T_proc_out,
                T_air_in=T_air_in_eff, T_air_out=T_air_out,
                fluid_proc=fluid,
                fin_type_key=fin_key,
                n_rows=n_rows, L_tube_m=L_tube_m, n_passes=n_passes,
                fan_type=fan_type, altitude_m=altitude_m,
                Rf_air=Rf_air, Rf_tube=Rf_tube, k_wall=k_wall,
                bay_width_m=bay_width_m,
            )
    else:
        geom = BundleGeometry(
            fin_type    = fin_key,
            n_rows      = n_rows,
            n_tubes_row = n_tubes_r,
            n_bays      = n_bays_r,
            L_tube_m    = L_tube_m,
            n_passes    = n_passes,
            fan_type    = fan_type,
        )
        result = rate_bundle(
            geom=geom,
            T_proc_in=T_proc_in, m_proc_kgs=m_proc_kgs,
            fluid_proc=fluid,
            T_air_in=T_air_in_eff, m_air_kgs=m_air_kgs,
            altitude_m=altitude_m,
            Rf_air=Rf_air, Rf_tube=Rf_tube, k_wall=k_wall,
        )
except Exception as exc:
    errors.append(f"Calculation error: {exc}")

# ── Hybrid cooling ─────────────────────────────────────────────────────────────
hybrid_result = None
if hybrid_on and result is not None and not errors:
    try:
        hmode = (HybridMode.PRE_COOLER
                 if hybrid_mode_str == HybridMode.PRE_COOLER.value
                 else HybridMode.DELUGE)
        T_air_out_for_hybrid = (
            result.T_air_out if hasattr(result, "T_air_out") else T_air_in + 20.0
        )
        hybrid_result = hybrid_cooling(
            mode       = hmode,
            m_air_kgs  = result.m_air_kgs,
            T_air_in   = T_air_in,
            T_air_out_dry = T_air_out_for_hybrid,
            RH_in_pct  = RH_in,
            Q_dry_kW   = result.Q_kW,
            T_proc_in  = T_proc_in,
            T_proc_out_dry = result.T_proc_out,
            fluid_cp   = fluid.cp,
            m_proc_kgs = result.m_proc_kgs,
            altitude_m = altitude_m,
            approach_K = approach_K,
        )
    except Exception as exc:
        errors.append(f"Hybrid cooling error: {exc}")

# ── Cooling loop ──────────────────────────────────────────────────────────────
pump_result = exp_result = pipe_result = None
loop_dp_pipe = 0.0
if loop_on and result is not None and not errors:
    try:
        fg = fin_geometry(fin_key)
        geom_for_loop = result.geom if hasattr(result, "geom") else None
        if geom_for_loop:
            dp_ache = ache_tube_dp(
                result.m_proc_kgs, fluid.rho, fluid.mu, fg.di_m,
                L_tube_m, geom_for_loop.n_passes,
                geom_for_loop.n_tubes_row, geom_for_loop.n_rows,
                geom_for_loop.n_bays,
            )
        else:
            dp_ache = 30.0   # fallback

        pipe_result = size_pipe(
            result.m_proc_kgs, fluid.rho, fluid.mu,
            v_max=v_tgt + 1.0, v_target=v_tgt,
            material=pipe_mat,
        )
        loop_dp_pipe = _pipe_dp(pipe_result, L_pipe)

        pump_result = size_pump(
            m_loop_kgs  = result.m_proc_kgs,
            rho         = fluid.rho,
            dP_ACHE_kPa = dp_ache,
            dP_pipe_kPa = loop_dp_pipe,
        )

        T_hot_loop = T_proc_in
        exp_result = size_expansion_vessel(
            V_system_L   = V_sys,
            T_cold_C     = T_cold,
            T_hot_C      = T_hot_loop,
            p_static_barg = p_stat,
            p_relief_barg = p_rel,
            fluid_name   = fluid_name,
        )
    except Exception as exc:
        errors.append(f"Cooling loop error: {exc}")


# ── Main area ─────────────────────────────────────────────────────────────────

st.markdown(f"<h1 style='color:{_BLUE};margin-bottom:2px'>AirHX</h1>", unsafe_allow_html=True)
st.caption(
    f"{'Design' if mode == 'Design' else 'Rating'} mode  ·  "
    f"{proj_name}  ·  {tag}  ·  {issued_for}"
)

if errors:
    for e in errors:
        st.error(e)

if result is not None:
    for w in result.warnings:
        st.warning(w)

# ── KLM / API 661 spec compliance checks ──────────────────────────────────────
if result is not None:
    spec_warns = []
    spec_infos = []

    T_air_in_used = result.T_air_in
    T_proc_out_r  = result.T_proc_out
    T_air_out_r   = result.T_air_out if hasattr(result, "T_air_out") else None

    # Minimum approach temperature
    # KLM conservative: ≥ 10°C; literature practical minimum: 5.6°C (10°F)
    approach = T_proc_out_r - T_air_in_used
    if approach < 5.6:
        spec_warns.append(
            f"Approach temperature {approach:.1f} K is below the practical industry minimum "
            f"of 5.6°C (10°F). Feasible but extremely expensive; review design."
        )
    elif approach < 10.0:
        spec_infos.append(
            f"Approach {approach:.1f} K is below KLM conservative minimum (10°C), "
            f"but above the industry practical minimum (5.6°C / 10°F). Verify economics."
        )

    # Air outlet T ≤ 60°C with fans running (KLM / all sources)
    if T_air_out_r is not None and T_air_out_r > 60.0:
        spec_warns.append(
            f"Air outlet {T_air_out_r:.1f}°C exceeds 60°C limit (fans operating) — "
            f"risk of damage to fan bearings and blade mechanism (KLM / API 661)."
        )

    # Forced draft required when approach ≥ 15°C (KLM)
    if approach >= 15.0 and "Induced" in result.geom.fan_type:
        spec_warns.append(
            f"KLM requires forced draft when T_proc_out − T_air_in ≥ 15°C "
            f"(here {approach:.1f} K). Switch to forced draft."
        )

    # V-type: warn if recirculation correction is non-zero or high G
    if "V-type" in result.geom.fan_type and recirc_dT > 0.0:
        spec_warns.append(
            "V-type / A-frame should NOT be used where hot-air recirculation is a concern "
            "(all literature sources agree). Consider flat forced-draft layout."
        )

    # Row count advisory (literature: >6 rows diminishing returns; KLM >8 rows limit)
    if result.geom.n_rows > 8:
        spec_warns.append(
            f"{result.geom.n_rows} rows exceeds KLM maximum of 8 — "
            "may exceed shipping and structural limits."
        )
    elif result.geom.n_rows > 6:
        spec_infos.append(
            f"{result.geom.n_rows} rows: rows beyond 6 give diminishing returns "
            "due to rising air temperature (literature consensus). Consider 6 rows max."
        )

    # API 661 fan coverage (already in engine warnings if <40%, add advisory for 40-60%)
    if 0.40 <= result.fan_coverage < 0.60:
        spec_infos.append(
            f"Fan coverage {result.fan_coverage*100:.0f}% meets API 661 minimum (40%) but is low. "
            f"Typical designs aim for ≥ 75%."
        )

    # Fan 10% reserve advisory (KLM)
    spec_infos.append(
        "Fan sizing (KLM §Air-Side item 11): specify variable-pitch fans "
        "capable of +10% airflow at constant speed."
    )

    if recirc_dT == 0.0:
        spec_infos.append(
            "Recirculation: if within 30 m of large buildings, add 1–2°C to air inlet T "
            "(KLM §Design Considerations). Near engine exhausts: up to +8°C."
        )

    for w in spec_warns:
        st.warning(f"⚠ Spec check — {w}")
    with st.expander("ℹ Spec notes (KLM / API 661)", expanded=False):
        for info in spec_infos:
            st.info(info)

# ── Goal-seek results ─────────────────────────────────────────────────────────
if "gs_error" in st.session_state:
    st.error(f"Goal seek error: {st.session_state.pop('gs_error')}")

if "gs_rows" in st.session_state and mode == "Design":
    gs_rows: list[GoalSeekRow] = st.session_state["gs_rows"]
    if gs_rows:
        with st.expander("**🔍 Goal Seek — design candidates**", expanded=True):
            st.caption(
                "All feasible (rows, passes) combinations for the current duty. "
                "Ranked by fewest bays, then air mass flux closest to 5 kg/(m²·s). "
                "Select a row and click **Apply** to load it into the geometry inputs."
            )

            # Build display DataFrame
            rec_idx = next((i for i, r in enumerate(gs_rows) if r.recommended), 0)
            df_data = []
            for r in gs_rows:
                flags = []
                if r.G_air > 12.0:  flags.append("⚠ G high")
                if r.G_air < 2.5:   flags.append("⚠ G low")
                if r.v_tube_ms < 0.3: flags.append("⚠ v low")
                df_data.append({
                    "★": "★" if r.recommended else "",
                    "Bays": r.n_bays,
                    "Rows": r.n_rows,
                    "Passes": r.n_passes_eff,
                    "U  W/m²K": f"{r.U_Wm2K:.1f}",
                    "G  kg/m²s": f"{r.G_air:.1f}",
                    "v  m/s": f"{r.v_tube_ms:.2f}",
                    "Re": f"{r.Re_tube:.0f}",
                    "A total m²": f"{r.A_total_m2:.0f}",
                    "Margin": f"{r.area_margin*100:+.0f}%",
                    "Fan kW": f"{r.P_fan_kW:.1f}",
                    "Notes": "  ".join(flags),
                })
            df = pd.DataFrame(df_data)

            # Colour the recommended row green
            def _style_row(row):
                if row["★"] == "★":
                    return [f"background-color:#d1fae5" for _ in row]
                return ["" for _ in row]

            st.dataframe(
                df.style.apply(_style_row, axis=1),
                use_container_width=True,
                hide_index=True,
                height=min(38 * (len(gs_rows) + 1) + 3, 420),
            )

            # Apply selector
            labels = [
                f"{r.n_bays} bay{'s' if r.n_bays>1 else ''} × "
                f"{r.n_rows} rows × "
                f"{r.n_passes_eff} passes"
                + (" ★ Recommended" if r.recommended else "")
                for r in gs_rows
            ]
            sel = st.selectbox("Apply design:", labels,
                               index=rec_idx, key="gs_sel")
            if st.button("Apply selected design", type="primary"):
                sel_idx = labels.index(sel)
                chosen  = gs_rows[sel_idx]
                st.session_state["n_rows"]   = chosen.n_rows
                st.session_state["n_passes"] = chosen.n_passes_eff
                st.rerun()

# ── ACHE diagram ──────────────────────────────────────────────────────────────
def _draw_bundle(res: BundleDesignResult | BundleRatingResult) -> go.Figure:
    """
    Two-panel schematic:
      Left  — SIDE ELEVATION (looking along bay-width direction):
              shows tube length (horizontal), bundle depth, headers, fans.
      Right — PLAN VIEW (from above): shows footprint (length × total width).

    Dimensions in metres throughout.
    """
    from plotly.subplots import make_subplots

    fg        = fin_geometry(res.geom.fin_type)
    nb        = res.geom.n_bays
    nr        = res.geom.n_rows
    Lt        = res.geom.L_tube_m
    bay_w     = res.geom.bay_width_m        # configurable bay width
    total_w   = nb * bay_w
    bundle_d  = nr * fg.pitch_m
    hdr_h     = 0.25
    is_vtype  = "V-type" in res.geom.fan_type
    forced    = "forced" in res.geom.fan_type.lower() or is_vtype

    # Use the fan diameter computed in the engine (stored in result)
    fan_d     = getattr(res, "fan_diam_m", None) or 3.658
    n_fans_bay = 2

    # Vertical layout (forced draft: fans below bundle)
    struct_h  = 0.50     # structural steel / fan pedestal above grade
    plenum_h  = max(0.60, 0.30 * bay_w)   # plenum between fan exit and bundle
    if forced:
        bundle_bot = struct_h + 0.40 + plenum_h    # 0.40 = fan ring height
        air_arrow_y0, air_arrow_y1 = 0.0, struct_h + 0.20
    else:
        bundle_bot = struct_h
        air_arrow_y0 = bundle_bot + hdr_h + bundle_d + hdr_h + 0.1
        air_arrow_y1 = air_arrow_y0 + 0.40 + plenum_h

    bundle_top = bundle_bot + hdr_h + bundle_d + hdr_h
    H_total    = bundle_top + (0.40 + plenum_h if not forced else 0.20)

    left_title = (
        "A-frame elevation (front view, 1 bay)"
        if is_vtype else
        f"Side elevation  (1 bay shown of {nb})"
    )
    fig = make_subplots(
        rows=1, cols=2,
        column_widths=[0.70, 0.30],
        subplot_titles=[left_title, "Plan view — footprint"],
        horizontal_spacing=0.06,
    )

    def sh(shape, row=1, col=1):
        shape["xref"] = f"x{'' if col==1 else col}"
        shape["yref"] = f"y{'' if col==1 else col}"
        fig.add_shape(shape, row=row, col=col)

    def ann(x, y, text, col=1, **kw):
        fig.add_annotation(x=x, y=y, text=text, showarrow=False,
                           xref=f"x{'' if col==1 else col}",
                           yref=f"y{'' if col==1 else col}", **kw)

    # ── LEFT panel ────────────────────────────────────────────────────────────
    if is_vtype:
        # ── V-type / A-frame: front elevation (looking along tube axis) ───────
        # Two bundles angled at 60° from horizontal, meeting at ridge.
        # Width shown = bundle length (Lt), height = A-frame profile.
        import math as _m
        angle_deg = 60.0
        angle_rad = _m.radians(angle_deg)
        # Half-span at base: bundle length / 2 (each leg)
        half_span = Lt / 2.0 * _m.cos(angle_rad)
        apex_h    = Lt / 2.0 * _m.sin(angle_rad)
        fan_cy    = 0.3        # fan centre height above grade
        cx        = Lt / 2.0   # centre of A-frame

        # Left bundle (from bottom-left to apex)
        sh(dict(type="path",
                path=f"M 0,{fan_cy + fan_d*0.15} L {cx-0.05},{fan_cy + apex_h} L {cx+0.05},{fan_cy + apex_h} L {half_span},{fan_cy + fan_d*0.15} Z",
                fillcolor="#f0f5fa", line_color="#b0b8c4", line_width=1))
        # Bundle fills
        for i in range(2):
            # Left leg row lines
            frac = (i + 0.5) / nr * (nr / 2)
            for leg, sign in [(-1, 1), (1, -1)]:
                xleg = cx + sign * (i + 0.5) * fg.pitch_m * _m.cos(angle_rad) / nr * nr
                yleg = fan_cy + apex_h - (i + 0.5) * fg.pitch_m * _m.sin(angle_rad) / nr * nr
        # Header boxes at ridge (top)
        sh(dict(type="rect", x0=cx - 0.15, x1=cx + 0.15,
                y0=fan_cy + apex_h - 0.05, y1=fan_cy + apex_h + hdr_h,
                fillcolor="#2d5f8a", line_color="#1e3a5f", line_width=1.5))
        # Fan circle at base
        sh(dict(type="circle", x0=cx - fan_d/2, y0=0, x1=cx + fan_d/2, y1=fan_d,
                fillcolor="#dce4ef", line_color="#2d5f8a", line_width=2))
        ann(cx, fan_d / 2, "⊕ FAN", col=1, font=dict(size=9, color="#2d5f8a"))
        # Hot-in / cool-out at bundle feet
        ann(0, fan_cy + fan_d * 0.15,
            f"← {res.T_proc_out:.0f}°C  out", col=1,
            font=dict(size=9, color="#3a6fa8"), align="right")
        ann(Lt, fan_cy + fan_d * 0.15,
            f"{res.T_proc_in:.0f}°C in →", col=1,
            font=dict(size=9, color="#b52b2b"), align="left")
        # Air arrows upward on both sides
        for ax_x in [Lt * 0.25, Lt * 0.75]:
            fig.add_annotation(
                x=ax_x, y=fan_cy + apex_h * 0.5,
                ax=ax_x, ay=0.1,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.2,
                arrowcolor="#4488aa", arrowwidth=2, text="",
            )
        ann(cx, -0.35, f"A-frame — L={Lt:.2f} m  bay_w={bay_w:.2f} m", col=1,
            font=dict(size=9, color="#555"))
        H_total = fan_cy + apex_h + hdr_h + 0.5

    else:
        # ── Flat bundle: side elevation ───────────────────────────────────────
        # Bottom header box
        sh(dict(type="rect", x0=0, x1=Lt,
                y0=bundle_bot, y1=bundle_bot + hdr_h,
                fillcolor="#2d5f8a", line_color="#1e3a5f", line_width=1.5))

        # Tube bundle (light fill)
        sh(dict(type="rect", x0=0, x1=Lt,
                y0=bundle_bot + hdr_h, y1=bundle_bot + hdr_h + bundle_d,
                fillcolor="#f0f5fa", line_color="#b0b8c4", line_width=1))

        # Tube rows as horizontal dashed lines
        for i in range(nr):
            ry = bundle_bot + hdr_h + (i + 0.5) * fg.pitch_m
            sh(dict(type="line", x0=0, x1=Lt, y0=ry, y1=ry,
                    line=dict(color="#aab4c8", width=1, dash="dot")))

        # Top header box
        sh(dict(type="rect", x0=0, x1=Lt,
                y0=bundle_bot + hdr_h + bundle_d,
                y1=bundle_bot + hdr_h + bundle_d + hdr_h,
                fillcolor="#2d5f8a", line_color="#1e3a5f", line_width=1.5))

        # Fans along tube length
        for i in range(n_fans_bay):
            cx   = Lt / n_fans_bay * (i + 0.5)
            if forced:
                cy = struct_h + 0.20
                fy0, fy1 = cy - fan_d / 2, cy + fan_d / 2
            else:
                cy   = bundle_top + plenum_h / 2 + 0.20
                fy0  = bundle_top + 0.1
                fy1  = bundle_top + 0.4 + plenum_h
            sh(dict(type="circle", x0=cx - fan_d/2, y0=fy0,
                    x1=cx + fan_d/2, y1=fy1,
                    fillcolor="#dce4ef", line_color="#2d5f8a", line_width=2))
            ann(cx, (fy0 + fy1) / 2, "⊕ FAN", col=1,
                font=dict(size=9, color="#2d5f8a"))

    if not is_vtype:
        # Air flow arrows (flat bundles only; V-type arrows drawn above)
        for ax_x in [Lt * 0.30, Lt * 0.70]:
            fig.add_annotation(
                x=ax_x, y=bundle_bot + hdr_h * 0.5 if forced else bundle_top + hdr_h,
                ax=ax_x, ay=0.0 if forced else H_total - 0.1,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.2,
                arrowcolor="#4488aa", arrowwidth=2, text="",
            )
        ann(Lt * 0.5, 0.05, "↑ Air in" if forced else "↑ Air out",
            col=1, font=dict(size=9, color="#4488aa"))

        ann(-0.4, bundle_bot + hdr_h * 0.5,
            f"Hot in\n{res.T_proc_in:.0f}°C", col=1,
            font=dict(size=9, color="#b52b2b"), align="right")
        ann(Lt + 0.4, bundle_bot + hdr_h * 0.5,
            f"Cool out\n{res.T_proc_out:.0f}°C", col=1,
            font=dict(size=9, color="#3a6fa8"), align="left")

        # Dimension annotations
        fig.add_annotation(
            x=Lt, y=-0.15, ax=0, ay=-0.15,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowcolor="#555", arrowwidth=1.5, text="",
        )
        fig.add_annotation(
            x=0, y=-0.15, ax=Lt, ay=-0.15,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowcolor="#555", arrowwidth=1.5, text="",
        )
        ann(Lt / 2, -0.32, f"L = {Lt:.2f} m", col=1, font=dict(size=9, color="#555"))
        ann(Lt + 0.6, bundle_top / 2, f"H ≈ {bundle_top:.1f} m", col=1,
            font=dict(size=9, color="#555"))

    # ── RIGHT: plan view (footprint) ──────────────────────────────────────────
    for ib in range(nb):
        y0b, y1b = ib * bay_w, (ib + 1) * bay_w
        sh(dict(type="rect", x0=0, x1=Lt, y0=y0b, y1=y1b,
                fillcolor="#e8f0f8", line_color="#2d5f8a", line_width=1.5),
           col=2)
        # Fan circles (plan view — each fan shown as circle)
        for j in range(n_fans_bay):
            cx2 = Lt / n_fans_bay * (j + 0.5)
            cy2 = y0b + bay_w / 2
            r2  = fan_d / 2
            sh(dict(type="circle",
                    x0=cx2 - r2, y0=cy2 - r2,
                    x1=cx2 + r2, y1=cy2 + r2,
                    fillcolor="#dce4ef", line_color="#2d5f8a", line_width=1.5),
               col=2)
        ann(Lt / 2, y0b + bay_w / 2,
            f"Bay {ib+1}", col=2,
            font=dict(size=8, color="#2d5f8a"))

    # Footprint dimension labels
    ann(Lt / 2, -0.3,
        f"L = {Lt:.2f} m", col=2,
        font=dict(size=8, color="#555"))
    ann(-0.5, total_w / 2,
        f"W = {total_w:.2f} m\n({nb}×{bay_w:.2f} m)",
        col=2, font=dict(size=8, color="#555"), align="right")

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_xaxes(visible=False, range=[-0.9, Lt + 1.0], row=1, col=1)
    fig.update_yaxes(visible=False, range=[-0.5, H_total + 0.3], row=1, col=1)
    fig.update_xaxes(visible=False, range=[-0.8, Lt + 0.4],
                     scaleanchor="y2", scaleratio=1, row=1, col=2)
    fig.update_yaxes(visible=False, range=[-0.5, total_w + 0.4],
                     row=1, col=2)
    fig.update_layout(
        showlegend=False,
        plot_bgcolor="white",
        margin=dict(l=10, r=10, t=35, b=10),
        height=340,
        font=dict(family="Arial", size=10),
    )
    return fig


if result is not None:
    st.plotly_chart(_draw_bundle(result), use_container_width=True)


# ── Bundle results ────────────────────────────────────────────────────────────
if result is not None:
    with st.expander("**Bundle sizing & heat transfer**", expanded=True):
        g = result.geom
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bays", g.n_bays)
        c2.metric("Rows", g.n_rows)
        c3.metric("Passes", g.n_passes)
        c4.metric("Tubes/row", g.n_tubes_row)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Tube length", f"{g.L_tube_m:.2f} m")
        c2.metric("Total tubes", g.n_tubes_total)
        c3.metric("Fin type", FIN_TYPE_LABELS.get(g.fin_type, g.fin_type).split("—")[0].strip())
        c4.metric("Fan type", g.fan_type)

        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("U (total area)", f"{result.htc.U:.1f} W/m²K")
        c2.metric("h air-side", f"{result.htc.h_air_eff:.1f} W/m²K")
        c3.metric("h tube-side", f"{result.htc.h_tube:.0f} W/m²K")
        c4.metric("Fin efficiency", f"{result.htc.eta_fin*100:.1f}%")

        c1, c2, c3 = st.columns(3)
        c1.metric("LMTD (CF)", f"{result.htc.LMTD:.1f} K")
        c2.metric("F-factor", f"{result.htc.F:.3f}")
        c3.metric("LMTD_eff", f"{result.htc.LMTD_eff:.1f} K")

        if isinstance(result, BundleDesignResult):
            st.divider()
            c1, c2, c3 = st.columns(3)
            c1.metric("Area required", f"{result.A_req_m2:.0f} m²")
            c2.metric("Area provided", f"{result.A_total_m2:.0f} m²")
            c3.metric("Area margin", f"{result.area_margin*100:.0f}%",
                      delta=f"+{result.area_margin*100:.0f}%" if result.area_margin >= 0 else None)

        if isinstance(result, BundleRatingResult):
            st.divider()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Duty Q", f"{result.Q_kW:.0f} kW")
            c2.metric("Process outlet T", f"{result.T_proc_out:.1f}°C")
            c3.metric("Effectiveness ε", f"{result.epsilon:.3f}")
            c4.metric("Total area", f"{result.A_total_m2:.0f} m²")

    with st.expander("**Air side**", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Air inlet T", f"{result.T_air_in:.1f}°C")
        c2.metric("Air outlet T", f"{result.T_air_out:.1f}°C" if hasattr(result, "T_air_out") else "—")
        c3.metric("Air mass flow", f"{result.m_air_kgs:.1f} kg/s")
        c4.metric("G_air", f"{result.G_air:.2f} kg/m²s")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ΔP air-side", f"{result.dP_air_Pa:.0f} Pa")
        c2.metric("Fan power", f"{result.P_fan_kW:.1f} kW")
        c3.metric("Process v_tube", f"{result.v_tube_ms:.2f} m/s")
        c4.metric("Re tube-side", f"{result.Re_tube:.0f}")

        c1, c2, c3, c4 = st.columns(4)
        fan_cov_pct = result.fan_coverage * 100
        c1.metric("Fan diameter",
                  f"{result.fan_diam_m:.2f} m  ({result.fan_diam_m/0.3048:.0f} ft)")
        c2.metric("Fan coverage",
                  f"{fan_cov_pct:.0f}%",
                  delta=f"{fan_cov_pct - 40:.0f}% vs API 661 min",
                  delta_color="normal" if fan_cov_pct >= 40 else "inverse")
        c3.metric("Bay width", f"{result.geom.bay_width_m:.3f} m")
        c4.metric("Face area", f"{result.geom.face_area_m2:.1f} m²")

    with st.expander("**Process stream**", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fluid",       fluid.name)
        c2.metric("T inlet",     f"{T_proc_in:.1f}°C")
        c3.metric("T outlet",    f"{result.T_proc_out:.1f}°C")
        c4.metric("Mass flow",   f"{result.m_proc_kgs:.2f} kg/s")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Density ρ",      f"{fluid.rho:.0f} kg/m³")
        c2.metric("Specific heat",  f"{fluid.cp:.0f} J/kg·K")
        c3.metric("Viscosity μ",    f"{fluid.mu*1000:.3f} mPa·s")
        c4.metric("Prandtl Pr",     f"{fluid.Pr:.2f}")


# ── Hybrid cooling ─────────────────────────────────────────────────────────────
if hybrid_on and hybrid_result is not None:
    with st.expander("**Hybrid evaporative cooling**", expanded=True):
        for n in hybrid_result.notes:
            st.info(n)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mode", hybrid_result.mode.value.split("(")[0].strip())
        c2.metric("Wet-bulb T", f"{hybrid_result.T_wb:.1f}°C")
        c3.metric("Eff. air inlet T", f"{hybrid_result.T_air_in_eff:.1f}°C",
                  delta=f"{hybrid_result.T_air_in_eff - hybrid_result.T_air_in_dry:.1f}°C")
        c4.metric("Ambient RH", f"{hybrid_result.RH_in_pct:.0f}%")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Dry duty",     f"{hybrid_result.Q_duty_dry_kW:.0f} kW")
        c2.metric("Wet duty",     f"{hybrid_result.Q_duty_wet_kW:.0f} kW",
                  delta=f"+{hybrid_result.Q_extra_kW:.0f} kW")
        c3.metric("Water use",    f"{hybrid_result.m_water_m3h:.2f} m³/h")
        c4.metric("Proc. out (wet)", f"{hybrid_result.T_proc_out_wet:.1f}°C",
                  delta=f"{hybrid_result.T_proc_out_wet - result.T_proc_out:.1f}°C")


# ── Cooling loop ──────────────────────────────────────────────────────────────
if loop_on and pump_result is not None:
    with st.expander("**Cooling loop — pump**", expanded=True):
        for n in pump_result.notes:
            st.warning(n)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Flow rate",     f"{pump_result.Q_m3h:.1f} m³/h")
        c2.metric("Total head",    f"{pump_result.H_m:.1f} m")
        c3.metric("Shaft power",   f"{pump_result.P_shaft_kW:.1f} kW")
        c4.metric("Motor size",    f"{pump_result.P_motor_kW:.0f} kW")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total ΔP",      f"{pump_result.dP_total_kPa:.0f} kPa")
        c2.metric("NPSH req.",     f"{pump_result.NPSH_req_m:.1f} m")
        c3.metric("Efficiency η",  f"{pump_result.eta_pump*100:.0f}%")
        c4.metric("",              "")

if loop_on and pipe_result is not None:
    with st.expander("**Cooling loop — pipework**", expanded=True):
        for n in pipe_result.notes:
            st.warning(n)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Main pipe DN",    f"DN{pipe_result.DN}")
        c2.metric("OD × wall",       f"{pipe_result.OD_mm:.1f} × {pipe_result.t_wall_mm:.1f} mm")
        c3.metric("Velocity",        f"{pipe_result.v_ms:.2f} m/s")
        c4.metric("Re",              f"{pipe_result.Re:.0f}")

        c1, c2, c3 = st.columns(3)
        c1.metric("ΔP / 100 m",     f"{pipe_result.dP_100m_kPa:.2f} kPa")
        c2.metric("Total pipe ΔP",  f"{loop_dp_pipe:.1f} kPa")
        c3.metric("Material",       pipe_result.material)

if loop_on and exp_result is not None:
    with st.expander("**Cooling loop — expansion vessel**", expanded=False):
        for n in exp_result.notes:
            st.warning(n)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vessel size",       f"{exp_result.V_vessel_L:.0f} L")
        c2.metric("Acceptance vol.",   f"{exp_result.V_acceptance_L:.0f} L")
        c3.metric("Expansion vol.",    f"{exp_result.V_expansion_L:.1f} L")
        c4.metric("Pre-charge p",      f"{exp_result.p_charge_bara:.2f} bara")

        c1, c2 = st.columns(2)
        c1.metric("Max pressure",      f"{exp_result.p_max_bara:.2f} bara")
        c2.metric("System volume",     f"{exp_result.V_system_L:.0f} L")


# ── Report generation ─────────────────────────────────────────────────────────
if gen_html and result is not None:
    try:
        from report import generate_datasheet_html
        st.session_state["report_html"] = generate_datasheet_html(
            proj_name=proj_name, tag=tag, issued_for=issued_for,
            mode=mode, result=result, fluid=fluid,
            hybrid_result=hybrid_result,
            pump_result=pump_result, exp_result=exp_result, pipe_result=pipe_result,
        )
        st.session_state["report_fname"] = f"{tag}_datasheet.html".replace(" ", "_")
        st.rerun()
    except Exception as exc:
        st.error(f"Report generation failed: {exc}")

if gen_docx and result is not None:
    try:
        from word_report import generate_word_report
        st.session_state["report_docx"] = generate_word_report(
            proj_name=proj_name, tag=tag, issued_for=issued_for,
            mode=mode, result=result, fluid=fluid,
            hybrid_result=hybrid_result,
            pump_result=pump_result, exp_result=exp_result, pipe_result=pipe_result,
        )
        st.session_state["report_docx_fname"] = f"{tag}_report.docx".replace(" ", "_")
        st.rerun()
    except Exception as exc:
        st.error(f"Report generation failed: {exc}")

st.markdown("---")
st.caption("AirHX — screening tool only. Not a certified design. For inquiry and FEED scoping.")
