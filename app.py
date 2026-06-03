"""
AirHX — Air-Cooled Heat Exchanger (ACHE / Fin-Fan) Design & Rating Tool

Screening-level tool for process engineers.
Not a certified design tool — for inquiry and FEED scoping only.
"""
import math
import streamlit as st
import plotly.graph_objects as go

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
    fan_type = st.radio("Fan arrangement", ["Forced draft", "Induced draft"],
                         horizontal=True, key="fan_type")

    c1, c2 = st.columns(2)
    n_rows   = c1.number_input("Rows",       value=6, min_value=1, max_value=12, step=1, key="n_rows")
    n_passes = c2.number_input("Passes",     value=2, min_value=1, max_value=12, step=1, key="n_passes")
    L_tube_m = st.number_input("Tube length [m]", value=9.144, min_value=3.0, step=0.305, key="L_tube_m")

    if mode == "Rating":
        n_bays_r  = st.number_input("Number of bays", value=1, min_value=1, max_value=20, step=1, key="n_bays_r")
        n_tubes_r = st.number_input("Tubes per row (per bay)", value=38, min_value=4, step=1, key="n_tubes_r")

    with st.expander("Fouling & wall"):
        Rf_air  = st.number_input("Air-side fouling [×10⁻⁶ m²K/W]",  value=9.0, step=1.0) * 1e-6
        Rf_tube = st.number_input("Tube-side fouling [×10⁻⁴ m²K/W]", value=1.76, step=0.1) * 1e-4
        k_wall  = st.number_input("Wall conductivity [W/m·K]", value=50.0, step=5.0)

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

result: BundleDesignResult | BundleRatingResult | None = None
errors: list[str] = []

try:
    if mode == "Design":
        T_air_out = st.session_state.get("T_air_out_d", 55.0)
        if T_air_out <= T_air_in:
            errors.append("Air outlet temperature must be > air inlet temperature.")
        elif T_proc_out >= T_proc_in:
            errors.append("Process outlet temperature must be < inlet temperature.")
        else:
            result = design_bundle(
                Q_kW=Q_kW,
                T_proc_in=T_proc_in, T_proc_out=T_proc_out,
                T_air_in=T_air_in,   T_air_out=T_air_out,
                fluid_proc=fluid,
                fin_type_key=fin_key,
                n_rows=n_rows, L_tube_m=L_tube_m, n_passes=n_passes,
                fan_type=fan_type, altitude_m=altitude_m,
                Rf_air=Rf_air, Rf_tube=Rf_tube, k_wall=k_wall,
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
            T_air_in=T_air_in, m_air_kgs=m_air_kgs,
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

# ── ACHE diagram ──────────────────────────────────────────────────────────────
def _draw_bundle(res: BundleDesignResult | BundleRatingResult) -> go.Figure:
    """Simple 2-D side-elevation schematic of one ACHE bay."""
    fg  = fin_geometry(res.geom.fin_type)
    nb  = res.geom.n_bays
    nr  = res.geom.n_rows
    Lt  = res.geom.L_tube_m
    tpr = res.geom.n_tubes_row
    pitch = fg.pitch_m * 1000  # mm

    bay_w = nb * (tpr * pitch)   # total width [mm]
    row_h = nr * pitch           # bundle depth [mm]

    fig = go.Figure()

    # Header boxes
    hdr_h = row_h * 0.15
    for side_y in [-(row_h + hdr_h) / 2, (row_h + hdr_h) / 2]:
        fig.add_shape(type="rect", x0=0, x1=bay_w, y0=side_y, y1=side_y + hdr_h,
                      fillcolor="#2d5f8a", line_color="#1e3a5f", line_width=1.5)

    # Tube rows (shown as horizontal lines)
    for i in range(nr):
        y = -row_h / 2 + (i + 0.5) * pitch
        fig.add_shape(type="line", x0=0, x1=bay_w, y0=y, y1=y,
                      line=dict(color="#aaaaaa", width=1, dash="dot"))

    # Fans (forced draft — below; induced — above)
    n_fans = nb * 2
    fan_w  = bay_w / n_fans * 0.6
    fan_y  = -row_h / 2 - hdr_h - pitch * 0.5
    for i in range(n_fans):
        cx = (i + 0.5) * bay_w / n_fans
        fig.add_shape(type="circle",
                      x0=cx - fan_w/2, y0=fan_y - fan_w/2,
                      x1=cx + fan_w/2, y1=fan_y + fan_w/2,
                      fillcolor="#dce4ef", line_color="#2d5f8a", line_width=1.5)
        fig.add_annotation(x=cx, y=fan_y, text="⊕", showarrow=False,
                           font=dict(size=10, color="#2d5f8a"))

    # Labels
    fig.add_annotation(x=bay_w/2, y=row_h/2 + hdr_h + pitch*0.3,
                       text=f"{nb} bay{'s' if nb>1 else ''} × {nr} rows × {tpr} tubes/row",
                       showarrow=False, font=dict(size=11, color="#1e3a5f"))
    fig.add_annotation(x=bay_w/2, y=fan_y - fan_w/2 - pitch*0.3,
                       text=f"{n_fans} fans ({res.geom.fan_type})",
                       showarrow=False, font=dict(size=10, color="#555"))

    # Tube-side arrows
    arrow_y_in  = row_h / 2 + hdr_h * 0.5
    arrow_y_out = -(row_h / 2 + hdr_h * 0.5)
    fig.add_annotation(x=bay_w * 0.1, y=arrow_y_in,
                       text=f"Hot in {res.T_proc_in:.0f}°C",
                       showarrow=True, ax=0, ay=-20,
                       font=dict(color="#b52b2b", size=10))
    fig.add_annotation(x=bay_w * 0.9, y=arrow_y_out,
                       text=f"Cool out {res.T_proc_out:.0f}°C",
                       showarrow=True, ax=0, ay=20,
                       font=dict(color="#3a6fa8", size=10))

    fig.update_layout(
        showlegend=False, margin=dict(l=20, r=20, t=20, b=20),
        xaxis=dict(visible=False, range=[-bay_w*0.1, bay_w*1.1]),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
        plot_bgcolor="white", height=280,
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
