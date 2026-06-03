"""
AirHX HTML datasheet (printable → PDF via browser).
"""
from __future__ import annotations
import html
from datetime import date

from engines import (
    BundleDesignResult, BundleRatingResult, FluidProps,
    HybridResult, FIN_TYPE_LABELS,
)
from engines.pump_sizing      import PumpResult
from engines.expansion_vessel import ExpVesselResult
from engines.pipe_sizing      import PipeSizeResult


# ── CSS ──────────────────────────────────────────────────────────────────────

_CSS = """
body{font-family:Arial,Helvetica,sans-serif;font-size:9.5pt;
     color:#1a1a1a;margin:12mm 14mm 14mm;line-height:1.4}
h1{font-size:14pt;color:#1e3a5f;margin:0 0 2px}
h2{font-size:10pt;color:#2d5f8a;margin:8px 0 3px;border-bottom:1px solid #b0b8c4}
.banner{background:#1e3a5f;color:#fff;padding:6px 10px;border-radius:3px;
        display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.banner-title{font-size:14pt;font-weight:bold}
.banner-meta{font-size:8.5pt;opacity:.9;text-align:right}
table{border-collapse:collapse;width:100%;margin-bottom:6px;font-size:9pt}
th{background:#dce4ef;color:#1e3a5f;padding:3px 6px;text-align:left;
   border:1px solid #b0b8c4;font-weight:600}
td{padding:2px 6px;border:1px solid #d0d8e0}
tr:nth-child(even) td{background:#f4f6fa}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:6px}
.panel{border:1px solid #b0b8c4;border-radius:3px;padding:5px 8px}
.panel-title{font-size:8.5pt;color:#2d5f8a;font-weight:bold;margin-bottom:3px}
.sec{margin-bottom:8px}
.sec-hdr{background:#1e3a5f;color:#fff;padding:2px 8px;font-size:9pt;
         font-weight:bold;border-radius:2px;margin-bottom:4px}
.ok{color:#166534;font-weight:bold} .warn{color:#92400e} .fail{color:#dc2626}
.note{font-size:8pt;color:#555;font-style:italic}
.kv td:first-child{font-weight:600;width:48%;color:#2d5f8a}
footer{font-size:7.5pt;color:#888;margin-top:12px;border-top:1px solid #ddd;
       padding-top:4px;text-align:center}
@media print{
  @page{size:A4 portrait;margin:12mm 14mm 14mm}
  .no-break{page-break-inside:avoid}
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _e(s) -> str:
    return html.escape(str(s))


def _kv(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in pairs)
    return f"<table class='kv'>{rows}</table>"


def _dt(headers: list[str], rows: list[list[str]]) -> str:
    ths  = "".join(f"<th>{_e(h)}</th>" for h in headers)
    trs  = "".join(
        "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"


def _sec(letter: str, title: str, content: str) -> str:
    return (f"<div class='sec no-break'>"
            f"<div class='sec-hdr'>{_e(letter)} — {_e(title)}</div>"
            f"{content}</div>")


def _panel(title: str, content: str) -> str:
    return (f"<div class='panel'>"
            f"<div class='panel-title'>{_e(title)}</div>{content}</div>")


# ── SVG side-elevation ────────────────────────────────────────────────────────

def _bundle_svg(result) -> str:
    """Simple SVG side-elevation of the ACHE bundle."""
    g   = result.geom
    nr  = g.n_rows
    nb  = g.n_bays
    tpr = g.n_tubes_row

    # Dimensions in SVG units (1 unit ≈ 2 mm approx)
    W, H = 400, 160
    bw = W * 0.75          # bundle width
    bd = H * 0.45          # bundle depth
    x0 = (W - bw) / 2
    y0 = (H - bd) / 2 - 15

    hdr_h = bd * 0.12
    row_sp = bd / nr

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{hdr_h:.1f}" '
        f'fill="#2d5f8a" rx="2"/>',
        f'<rect x="{x0:.1f}" y="{y0 + bd - hdr_h:.1f}" width="{bw:.1f}" height="{hdr_h:.1f}" '
        f'fill="#2d5f8a" rx="2"/>',
    ]
    for i in range(nr):
        ry = y0 + hdr_h + (i + 0.5) * (bd - 2 * hdr_h) / nr
        lines.append(
            f'<line x1="{x0:.1f}" y1="{ry:.1f}" x2="{x0+bw:.1f}" y2="{ry:.1f}" '
            f'stroke="#aaa" stroke-width="1" stroke-dasharray="4 2"/>'
        )
    # Fan circles
    n_fans = nb * 2
    for i in range(n_fans):
        cx = x0 + (i + 0.5) * bw / n_fans
        cy = y0 + bd + hdr_h + 14
        r  = min(bw / n_fans * 0.35, 16)
        lines.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="#dce4ef" stroke="#2d5f8a" stroke-width="1.5"/>'
        )
        lines.append(
            f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" '
            f'font-size="10" fill="#2d5f8a">⊕</text>'
        )
    # Labels
    lines.append(
        f'<text x="{W/2:.1f}" y="{y0 - 4:.1f}" text-anchor="middle" '
        f'font-size="9" fill="#1e3a5f">'
        f'{nb} bay{"s" if nb>1 else ""} × {nr} rows × {tpr} tubes/row  |  '
        f'{g.fan_type}</text>'
    )
    lines.append("</svg>")
    return "\n".join(lines)


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_datasheet_html(
    proj_name: str, tag: str, issued_for: str,
    mode: str,
    result,
    fluid: FluidProps,
    hybrid_result=None,
    pump_result=None,
    exp_result=None,
    pipe_result=None,
) -> str:

    today = date.today().strftime("%d %b %Y")
    g     = result.geom
    htc   = result.htc
    is_design = isinstance(result, BundleDesignResult)

    # ── Banner ───────────────────────────────────────────────────────────────
    banner = (
        f"<div class='banner'>"
        f"<div>"
        f"<div class='banner-title'>AirHX — Air-Cooled Heat Exchanger</div>"
        f"<div style='font-size:9pt;opacity:.8'>{_e(mode)} mode · Screening level</div>"
        f"</div>"
        f"<div class='banner-meta'>"
        f"<b>{_e(proj_name)}</b><br/>"
        f"Tag: {_e(tag)}<br/>"
        f"Issued for: {_e(issued_for)}<br/>"
        f"Date: {today}"
        f"</div></div>"
    )

    # ── Section A: Design basis ──────────────────────────────────────────────
    sec_a = _sec("A", "Design basis", _kv([
        ("Calculation mode",        mode),
        ("Tube-side fluid",         fluid.name),
        ("Process inlet T",         f"{result.T_proc_in:.1f} °C"),
        ("Process outlet T",        f"{result.T_proc_out:.1f} °C"),
        ("Air inlet T (ambient)",   f"{result.T_air_in:.1f} °C"),
        ("Air outlet T",            f"{result.T_air_out:.1f} °C" if hasattr(result, "T_air_out") else "—"),
        ("Heat duty Q",             f"{result.Q_kW:.0f} kW  ({result.Q_kW/1000:.3f} MW)"),
        ("Process mass flow",       f"{result.m_proc_kgs:.2f} kg/s  ({result.m_proc_kgs*3600:.0f} kg/h)"),
    ]))

    # ── Section B: Bundle geometry ────────────────────────────────────────────
    sec_b = _sec("B", "Bundle geometry", _kv([
        ("Fin type",                FIN_TYPE_LABELS.get(g.fin_type, g.fin_type)),
        ("Number of bays",          str(g.n_bays)),
        ("Rows per bay",            str(g.n_rows)),
        ("Tubes per row (per bay)", str(g.n_tubes_row)),
        ("Tube-side passes",        str(g.n_passes)),
        ("Tube length",             f"{g.L_tube_m:.3f} m"),
        ("Total tubes",             str(g.n_tubes_total)),
        ("Fan arrangement",         g.fan_type),
    ]))

    # ── Section C: Thermal performance ────────────────────────────────────────
    perf_rows = [
        ("Overall U (total ext. area)",  f"{htc.U:.1f} W/m²K"),
        ("Air-side HTC (total area)",    f"{htc.h_air_eff:.1f} W/m²K"),
        ("Air-side HTC (bare tube)",     f"{htc.h_air_bare:.1f} W/m²K"),
        ("Fin efficiency η_fin",         f"{htc.eta_fin*100:.1f}%"),
        ("Overall surface eff. η_o",     f"{htc.eta_o*100:.1f}%"),
        ("Tube-side HTC",               f"{htc.h_tube:.0f} W/m²K"),
        ("LMTD (counter-flow)",         f"{htc.LMTD:.1f} K"),
        ("F-factor (cross-flow)",       f"{htc.F:.3f}"),
        ("Effective LMTD",              f"{htc.LMTD_eff:.1f} K"),
    ]
    if is_design:
        perf_rows += [
            ("Required area",           f"{result.A_req_m2:.0f} m²"),
            ("Provided area",           f"{result.A_total_m2:.0f} m²"),
            ("Area margin",             f"{result.area_margin*100:.0f}%"),
        ]
    else:
        perf_rows += [
            ("Total area",              f"{result.A_total_m2:.0f} m²"),
            ("Effectiveness ε",         f"{result.epsilon:.3f}"),
        ]
    sec_c = _sec("C", "Thermal performance", _kv(perf_rows))

    # ── Section D: Air side ───────────────────────────────────────────────────
    sec_d = _sec("D", "Air side", _kv([
        ("Air mass flow",           f"{result.m_air_kgs:.1f} kg/s"),
        ("Air mass flux G",         f"{result.G_air:.2f} kg/(m²·s)"),
        ("Air-side ΔP",             f"{result.dP_air_Pa:.0f} Pa"),
        ("Fan power (est.)",        f"{result.P_fan_kW:.1f} kW"),
        ("Tube velocity",           f"{result.v_tube_ms:.2f} m/s"),
        ("Tube-side Re",            f"{result.Re_tube:.0f}"),
    ]))

    # ── Section E: Hybrid cooling (optional) ──────────────────────────────────
    sec_e = ""
    if hybrid_result is not None:
        sec_e = _sec("E", "Hybrid evaporative cooling", _kv([
            ("Mode",                    hybrid_result.mode.value),
            ("Ambient dry-bulb T",      f"{hybrid_result.T_air_in_dry:.1f} °C"),
            ("Wet-bulb T",              f"{hybrid_result.T_wb:.1f} °C"),
            ("Effective air inlet T",   f"{hybrid_result.T_air_in_eff:.1f} °C"),
            ("Dry duty",                f"{hybrid_result.Q_duty_dry_kW:.0f} kW"),
            ("Wet duty",                f"{hybrid_result.Q_duty_wet_kW:.0f} kW"),
            ("Extra duty",              f"{hybrid_result.Q_extra_kW:.0f} kW"),
            ("Water consumption",       f"{hybrid_result.m_water_m3h:.2f} m³/h"),
            ("Process outlet T (wet)",  f"{hybrid_result.T_proc_out_wet:.1f} °C"),
        ]))

    # ── Section F: Cooling loop ────────────────────────────────────────────────
    sec_f = ""
    loop_rows = []
    if pump_result is not None:
        loop_rows += [
            ("Pump flow",               f"{pump_result.Q_m3h:.1f} m³/h"),
            ("Pump head",               f"{pump_result.H_m:.1f} m"),
            ("Shaft power",             f"{pump_result.P_shaft_kW:.1f} kW"),
            ("Motor size (standard)",   f"{pump_result.P_motor_kW:.0f} kW"),
        ]
    if pipe_result is not None:
        loop_rows += [
            ("Main pipe DN",            f"DN{pipe_result.DN} ({pipe_result.OD_mm:.1f} × {pipe_result.t_wall_mm:.1f} mm)"),
            ("Pipe velocity",           f"{pipe_result.v_ms:.2f} m/s"),
            ("ΔP / 100 m",              f"{pipe_result.dP_100m_kPa:.2f} kPa"),
        ]
    if exp_result is not None:
        loop_rows += [
            ("Expansion vessel size",   f"{exp_result.V_vessel_L:.0f} L"),
            ("Acceptance volume",       f"{exp_result.V_acceptance_L:.0f} L"),
            ("Pre-charge pressure",     f"{exp_result.p_charge_bara:.2f} bara"),
        ]
    if loop_rows:
        sec_f = _sec("F", "Cooling loop sizing", _kv(loop_rows))

    # ── Section G: Warnings ────────────────────────────────────────────────────
    warn_items = result.warnings or []
    if hybrid_result:
        warn_items += hybrid_result.notes
    if warn_items:
        w_html = "<ul>" + "".join(f"<li class='warn'>{_e(w)}</li>" for w in warn_items) + "</ul>"
    else:
        w_html = "<p class='ok'>No engineering warnings.</p>"
    sec_g = _sec("G", "Notes & findings", w_html +
                 "<p class='note'>AirHX is a screening tool only. "
                 "Results are approximate and require verification by a qualified engineer. "
                 "Not for certified design use.</p>")

    # ── SVG sketch ────────────────────────────────────────────────────────────
    sketch = (
        "<div style='text-align:center;margin:8px 0'>"
        + _bundle_svg(result)
        + "<br/><span class='note'>ACHE side-elevation schematic (not to scale)</span>"
        + "</div>"
    )

    body = (banner + sketch + sec_a + sec_b + sec_c + sec_d
            + sec_e + sec_f + sec_g)

    footer = (
        f"<footer>Generated {today} by AirHX — "
        f"screening tool only, not a certified design. "
        f"Project: {_e(proj_name)} · Tag: {_e(tag)}</footer>"
    )

    return (
        "<!DOCTYPE html><html><head>"
        "<meta charset='utf-8'/>"
        f"<style>{_CSS}</style>"
        f"<title>AirHX Datasheet — {_e(tag)}</title>"
        "</head><body>"
        + body + footer
        + "</body></html>"
    )
