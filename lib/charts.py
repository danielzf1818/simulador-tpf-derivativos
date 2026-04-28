"""Charts for the simulator — dark theme, full-width optimized."""

from __future__ import annotations
import plotly.graph_objects as go
from .instruments import INSTRUMENTS
from .scenarios import calc_scenario_delta, calc_leg_pnl
from .curves import (
    flat_forward_curve, flat_forward_curve_lin360,
    build_di_vertices, build_dap_vertices, build_frc_vertices,
    build_forward_curve, flat_forward_lin360,
)

COLORS = ["#58a6ff", "#f85149", "#3fb950", "#d29922", "#bc8cff", "#f778ba"]

_GRID = "rgba(100,100,100,0.15)"
_ZERO = "rgba(100,100,100,0.4)"
_GREEN = "#3fb950"
_RED = "#f85149"
_BLUE = "#58a6ff"
_MUTED = "#8b949e"


def _base_layout(title: str = "", height: int = 350) -> dict:
    return dict(
        template="none",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="Inter, -apple-system, BlinkMacSystemFont, sans-serif",
            size=12, color="#c9d1d9"),
        title=dict(text=title, font=dict(size=13, color="#e6edf3"),
                   x=0, xanchor="left", y=0.98, yanchor="top"),
        margin=dict(l=60, r=20, t=60, b=50),
        height=height,
        legend=dict(
            orientation="h", yanchor="top", y=1.12, xanchor="left", x=0,
            font=dict(color="#c9d1d9", size=11),
            itemwidth=30, tracegroupgap=4),
    )


def _is_rate_leg(l: dict) -> bool:
    info = l.get("info")
    if not info:
        info = INSTRUMENTS.get(l.get("instrument"))
    return info is not None and info.conv != "price"


def _rate_du_range(legs: list[dict]) -> tuple[int, int]:
    rate_legs = [l for l in legs if _is_rate_leg(l)]
    if not rate_legs:
        return 0, 0
    return min(l["du"] for l in rate_legs), max(l["du"] for l in rate_legs)


def _leg_delta(l: dict, du_min: int, du_max: int,
               scenario_key: str, magnitude: float) -> float:
    if not _is_rate_leg(l):
        return 0.0
    return calc_scenario_delta(l["du"], du_min, du_max, scenario_key, magnitude)


def _dir_label(l: dict) -> str:
    return "C" if l["direction"] == "C" else "V"


def _build_di_curve(di1_curve):
    """Converte lista de contratos B3 em (dus, rates) ordenados."""
    from lib.calendar import du_entre, default_liq_date
    from datetime import date
    data_neg = date.today()
    liq = default_liq_date(data_neg)
    pairs = []
    for c in di1_curve:
        rate = c.get("last", 0)
        if rate <= 0:
            rate = c.get("ajuste", 0)
        if rate <= 0:
            continue
        vp = c["vcto"].split("-")
        vd = date(int(vp[0]), int(vp[1]), int(vp[2]))
        du = du_entre(liq, vd)
        if du > 0:
            pairs.append((du, rate))
    pairs.sort()
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _build_smooth_curve(di1_curve, du_step: int = 5):
    """Constroi curva DI suave via flat forward interpolation."""
    from lib.calendar import default_liq_date
    from datetime import date
    liq = default_liq_date(date.today())
    vertices = build_di_vertices(di1_curve, liq)
    if not vertices:
        return [], []
    smooth = flat_forward_curve(vertices, du_step)
    return [p[0] for p in smooth], [p[1] for p in smooth]


def _build_smooth_dap_curve(dap_contracts, du_step: int = 5):
    """Constroi curva DAP suave via flat forward interpolation."""
    from lib.calendar import default_liq_date
    from datetime import date
    liq = default_liq_date(date.today())
    vertices = build_dap_vertices(dap_contracts, liq)
    if not vertices:
        return [], []
    smooth = flat_forward_curve(vertices, du_step)
    return [p[0] for p in smooth], [p[1] for p in smooth]


_DAP_COLOR = "#d29922"


def chart_curva_antes_depois(legs: list[dict], scenario_key: str,
                              magnitude: float, di1_curve: list = None,
                              dap_curve: list = None) -> go.Figure:
    """Curva de juros COMPLETA antes/depois do choque.

    Plota curva DI interpolada via flat forward (suave) e opcionalmente
    a curva DAP quando NTN-B esta na operacao. Pernas destacadas como pontos.
    """
    fig = go.Figure()

    rate_legs = sorted(
        [l for l in legs if _is_rate_leg(l)], key=lambda l: l["du"])

    if rate_legs:
        du_min_legs = min(l["du"] for l in rate_legs)
        du_max_legs = max(l["du"] for l in rate_legs)
    else:
        du_min_legs, du_max_legs = 0, 1000

    if di1_curve:
        try:
            smooth_dus, smooth_rates = _build_smooth_curve(di1_curve, du_step=5)

            if smooth_dus:
                fig.add_trace(go.Scatter(
                    x=smooth_dus, y=smooth_rates, mode="lines",
                    name="DI Antes",
                    line=dict(color=_MUTED, width=1.5, dash="dash"),
                    hovertemplate="DU: %{x}<br>Taxa: %{y:.3f}%<extra>Antes</extra>",
                ))

                curve_deltas = [calc_scenario_delta(du, du_min_legs, du_max_legs, scenario_key, magnitude)
                                for du in smooth_dus]
                curve_after = [r + d / 100 for r, d in zip(smooth_rates, curve_deltas)]

                fig.add_trace(go.Scatter(
                    x=smooth_dus, y=curve_after, mode="lines",
                    name="DI Depois",
                    line=dict(color=_BLUE, width=2),
                    customdata=curve_deltas,
                    hovertemplate="DU: %{x}<br>Taxa: %{y:.3f}%<br>Delta: %{customdata:+.1f}bp<extra>Depois</extra>",
                ))

                fig.add_trace(go.Scatter(
                    x=smooth_dus + smooth_dus[::-1],
                    y=curve_after + smooth_rates[::-1],
                    fill="toself", fillcolor="rgba(88,166,255,0.06)",
                    line=dict(width=0), showlegend=False, hoverinfo="skip",
                ))
        except Exception:
            pass

    has_ntnb = any(l["instrument"] == "NTN-B" for l in legs)
    has_dap_leg = any(l["instrument"] == "DAP" for l in legs)
    if dap_curve and (has_ntnb or has_dap_leg):
        try:
            dap_dus, dap_rates = _build_smooth_dap_curve(dap_curve, du_step=5)
            if dap_dus:
                fig.add_trace(go.Scatter(
                    x=dap_dus, y=dap_rates, mode="lines",
                    name="DAP Antes",
                    line=dict(color=_DAP_COLOR, width=1.5, dash="dot"),
                    hovertemplate="DU: %{x}<br>Taxa real: %{y:.3f}%<extra>DAP Antes</extra>",
                ))

                dap_deltas = [calc_scenario_delta(du, du_min_legs, du_max_legs, scenario_key, magnitude)
                              for du in dap_dus]
                dap_after = [r + d / 100 for r, d in zip(dap_rates, dap_deltas)]

                fig.add_trace(go.Scatter(
                    x=dap_dus, y=dap_after, mode="lines",
                    name="DAP Depois",
                    line=dict(color=_DAP_COLOR, width=2),
                    customdata=dap_deltas,
                    hovertemplate="DU: %{x}<br>Taxa real: %{y:.3f}%<br>Delta: %{customdata:+.1f}bp<extra>DAP Depois</extra>",
                ))
        except Exception:
            pass

    if rate_legs:
        _positions = ["top center", "bottom center", "top right", "bottom right",
                      "top left", "bottom left"]
        for i, l in enumerate(rate_legs):
            delta = calc_scenario_delta(l["du"], du_min_legs, du_max_legs, scenario_key, magnitude)
            after = l["tax_fin"] + delta / 100
            lbl = f"{_dir_label(l)} {l['instrument']} {l['parsed']['label']}"
            pos = _positions[i % len(_positions)]
            color = COLORS[i % len(COLORS)]

            fig.add_trace(go.Scatter(
                x=[l["du"]], y=[l["tax_fin"]], mode="markers",
                name=lbl,
                marker=dict(size=8, color=color, symbol="circle-open", line=dict(width=2, color=color)),
                hovertemplate=f"{lbl}<br>DU: %{{x}}<br>Taxa: %{{y:.3f}}%<extra>Antes</extra>",
                legendgroup=lbl, showlegend=True,
            ))
            fig.add_trace(go.Scatter(
                x=[l["du"]], y=[after], mode="markers+text",
                marker=dict(size=10, color=color, symbol="circle"),
                text=[f"{lbl} {delta:+.0f}bp"],
                textposition=pos, textfont=dict(size=10, color=color),
                hovertemplate=f"{lbl}<br>DU: %{{x}}<br>Taxa: %{{y:.3f}}%<br>Delta: {delta:+.1f}bp<extra>Depois</extra>",
                legendgroup=lbl, showlegend=False,
            ))

    fig.update_layout(
        **_base_layout("Curva de Juros — Flat Forward", 450),
        xaxis=dict(title="Prazo (DU)", gridcolor=_GRID, rangemode="tozero"),
        yaxis=dict(title="Taxa (% a.a.)", tickformat=".2f", gridcolor=_GRID),
    )
    return fig


def chart_pnl_barras(legs: list[dict], scenario_key: str,
                      magnitude: float,
                      delta_fx_pct: float = 0.0,
                      delta_ipca_bps: float = 0.0,
                      delta_cupom_bps: float = 0.0) -> go.Figure:
    du_min, du_max = _rate_du_range(legs)

    names, pnls, colors = [], [], []
    for l in legs:
        delta = _leg_delta(l, du_min, du_max, scenario_key, magnitude)
        pnl = calc_leg_pnl(l, delta,
                           delta_fx_pct=delta_fx_pct,
                           delta_ipca_bps=delta_ipca_bps,
                           delta_cupom_bps=delta_cupom_bps)
        names.append(f"{_dir_label(l)} {l['instrument']} {l['parsed']['label']}")
        pnls.append(pnl)
        colors.append(_GREEN if pnl >= 0 else _RED)

    total = sum(pnls)
    names.append("TOTAL")
    pnls.append(total)
    colors.append(_BLUE)

    fig = go.Figure(go.Bar(
        y=names, x=pnls, orientation="h",
        marker_color=colors,
        text=[f"R$ {v:+,.0f}" for v in pnls],
        textposition="outside", textfont=dict(size=11),
    ))
    fig.update_layout(
        **_base_layout("P&L por Perna (R$)", 50 + len(names) * 45),
        xaxis=dict(
            title="P&L (R$)", zeroline=True,
            zerolinecolor=_ZERO, gridcolor=_GRID),
        yaxis=dict(autorange="reversed"),
        showlegend=False,
    )
    return fig


def chart_pnl_consolidado(legs: list[dict],
                           delta_fx_pct: float = 0.0,
                           delta_ipca_bps: float = 0.0,
                           delta_cupom_bps: float = 0.0) -> go.Figure:
    deltas_range = list(range(-15, 16))
    total_pnl = []
    for d in deltas_range:
        t = 0.0
        for l in legs:
            leg_d = d if _is_rate_leg(l) else 0.0
            t += calc_leg_pnl(l, leg_d,
                              delta_fx_pct=delta_fx_pct,
                              delta_ipca_bps=delta_ipca_bps,
                              delta_cupom_bps=delta_cupom_bps)
        total_pnl.append(t)

    colors = [_GREEN if v >= 0 else _RED for v in total_pnl]

    fig = go.Figure(go.Bar(x=deltas_range, y=total_pnl, marker_color=colors))
    fig.update_layout(
        **_base_layout("P&L Consolidado — Shift Paralelo", 350),
        xaxis=dict(title="Delta (bps)", dtick=5, gridcolor=_GRID),
        yaxis=dict(
            title="P&L (R$)", zeroline=True,
            zerolinecolor=_ZERO, gridcolor=_GRID),
        showlegend=False,
    )
    return fig


def chart_pnl_por_perna(legs: list[dict],
                         delta_fx_pct: float = 0.0,
                         delta_ipca_bps: float = 0.0,
                         delta_cupom_bps: float = 0.0) -> go.Figure:
    deltas_range = list(range(-15, 16))
    fig = go.Figure()
    for i, l in enumerate(legs):
        name = f"{_dir_label(l)} {l['instrument']} {l['parsed']['label']}"
        if _is_rate_leg(l):
            pnls = [calc_leg_pnl(l, d,
                                 delta_fx_pct=delta_fx_pct,
                                 delta_ipca_bps=delta_ipca_bps,
                                 delta_cupom_bps=delta_cupom_bps)
                    for d in deltas_range]
        else:
            pnls = [calc_leg_pnl(l, 0,
                                 delta_fx_pct=delta_fx_pct,
                                 delta_ipca_bps=delta_ipca_bps,
                                 delta_cupom_bps=delta_cupom_bps)
                    for _ in deltas_range]
        fig.add_trace(go.Scatter(
            x=deltas_range, y=pnls, mode="lines", name=name,
            line=dict(color=COLORS[i % len(COLORS)], width=2),
        ))
    fig.update_layout(
        **_base_layout("P&L por Perna — Shift Paralelo", 350),
        xaxis=dict(title="Delta (bps)", dtick=5, gridcolor=_GRID),
        yaxis=dict(
            title="P&L (R$)", zeroline=True,
            zerolinecolor=_ZERO, gridcolor=_GRID),
    )
    return fig


_FRC_COLOR = "#bc8cff"
_FWD_COLOR = "#3fb950"


def chart_cupom_cambial(frc_contracts: list, delta_cupom_bps: float = 0.0,
                         legs: list[dict] = None) -> go.Figure:
    """Curva de cupom cambial (FRC) antes/depois do choque."""
    from lib.calendar import default_liq_date
    from datetime import date

    fig = go.Figure()
    liq = default_liq_date(date.today())
    vertices = build_frc_vertices(frc_contracts, liq)
    if not vertices:
        fig.update_layout(**_base_layout("Cupom Cambial — sem dados", 400))
        return fig

    smooth = flat_forward_curve_lin360(vertices, dc_step=5)
    if not smooth:
        fig.update_layout(**_base_layout("Cupom Cambial — sem dados", 400))
        return fig

    dcs_before = [p[0] for p in smooth]
    rates_before = [p[1] for p in smooth]

    fig.add_trace(go.Scatter(
        x=dcs_before, y=rates_before, mode="lines",
        name="Cupom Antes",
        line=dict(color=_MUTED, width=1.5, dash="dash"),
        hovertemplate="DC: %{x}<br>Cupom: %{y:.3f}%<extra>Antes</extra>",
    ))

    rates_after = [r + delta_cupom_bps / 100 for r in rates_before]
    fig.add_trace(go.Scatter(
        x=dcs_before, y=rates_after, mode="lines",
        name="Cupom Depois",
        line=dict(color=_FRC_COLOR, width=2),
        hovertemplate="DC: %{x}<br>Cupom: %{y:.3f}%<extra>Depois</extra>",
    ))

    fig.add_trace(go.Scatter(
        x=dcs_before + dcs_before[::-1],
        y=rates_after + rates_before[::-1],
        fill="toself", fillcolor="rgba(188,140,255,0.06)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))

    vert_dcs = [v[0] for v in vertices]
    vert_rates = [v[1] for v in vertices]
    fig.add_trace(go.Scatter(
        x=vert_dcs, y=vert_rates, mode="markers",
        name="Vertices FRC",
        marker=dict(size=5, color=_FRC_COLOR, symbol="diamond"),
        hovertemplate="DC: %{x}<br>Cupom: %{y:.3f}%<extra>Vertice</extra>",
    ))

    if legs:
        cupom_legs = [l for l in legs if l["instrument"] in ("FRC", "DDI")]
        for i, l in enumerate(cupom_legs):
            lbl = f"{_dir_label(l)} {l['instrument']} {l['parsed']['label']}"
            fig.add_trace(go.Scatter(
                x=[l["dc"]], y=[l["tax_fin"]], mode="markers+text",
                name=lbl,
                marker=dict(size=10, color=_FRC_COLOR, symbol="circle"),
                text=[lbl], textposition="top center",
                textfont=dict(size=10, color=_FRC_COLOR),
                hovertemplate=f"{lbl}<br>DC: %{{x}}<br>Taxa: %{{y:.3f}}%<extra></extra>",
            ))

    fig.update_layout(
        **_base_layout("Cupom Cambial Limpo (FRC) — lin360", 400),
        xaxis=dict(title="Prazo (DC)", gridcolor=_GRID),
        yaxis=dict(title="Cupom (% a.a. lin360)", tickformat=".2f", gridcolor=_GRID),
    )
    return fig


def chart_dol_forward(di1_contracts: list, frc_contracts: list,
                       spot: float, delta_pre_bps: float = 0.0,
                       delta_cupom_bps: float = 0.0,
                       delta_fx_pct: float = 0.0,
                       legs: list[dict] = None) -> go.Figure:
    """Curva de dolar forward implicito antes/depois dos choques."""
    from lib.calendar import default_liq_date
    from datetime import date

    fig = go.Figure()
    liq = default_liq_date(date.today())
    di_verts = build_di_vertices(di1_contracts, liq)
    frc_verts = build_frc_vertices(frc_contracts, liq)

    if not di_verts or not frc_verts or spot <= 0:
        fig.update_layout(**_base_layout("Dolar Forward — sem dados", 400))
        return fig

    fwd_curve = build_forward_curve(di_verts, frc_verts, spot, liq)
    if not fwd_curve:
        fig.update_layout(**_base_layout("Dolar Forward — sem dados", 400))
        return fig

    dus = [p[0] for p in fwd_curve]
    fwds_before = [p[2] for p in fwd_curve]

    fig.add_trace(go.Scatter(
        x=dus, y=fwds_before, mode="lines",
        name="Forward Antes",
        line=dict(color=_MUTED, width=1.5, dash="dash"),
        hovertemplate="DU: %{x}<br>Fwd: R$ %{y:.4f}<extra>Antes</extra>",
    ))

    spot_after = spot * (1 + delta_fx_pct / 100)
    di_verts_after = [(du, r + delta_pre_bps / 100) for du, r in di_verts]
    frc_verts_after = [(dc, r + delta_cupom_bps / 100) for dc, r in frc_verts]
    fwd_after_curve = build_forward_curve(di_verts_after, frc_verts_after, spot_after, liq)
    fwds_after = [p[2] for p in fwd_after_curve] if fwd_after_curve else fwds_before

    fig.add_trace(go.Scatter(
        x=dus[:len(fwds_after)], y=fwds_after, mode="lines",
        name="Forward Depois",
        line=dict(color=_FWD_COLOR, width=2),
        hovertemplate="DU: %{x}<br>Fwd: R$ %{y:.4f}<extra>Depois</extra>",
    ))

    fig.add_trace(go.Scatter(
        x=dus[:len(fwds_after)] + dus[:len(fwds_after)][::-1],
        y=fwds_after + fwds_before[:len(fwds_after)][::-1],
        fill="toself", fillcolor="rgba(63,185,80,0.06)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))

    fig.add_hline(y=spot, line_dash="dot", line_color=_MUTED,
                  annotation_text=f"Spot {spot:.4f}", annotation_font_color=_MUTED)

    if legs:
        dol_legs = [l for l in legs if l["instrument"] == "DOL"]
        for l in dol_legs:
            lbl = f"{_dir_label(l)} DOL {l['parsed']['label']}"
            fig.add_trace(go.Scatter(
                x=[l["du"]], y=[l["taxa"] / 1000], mode="markers+text",
                name=lbl,
                marker=dict(size=10, color=_FWD_COLOR, symbol="circle"),
                text=[lbl], textposition="top center",
                textfont=dict(size=10, color=_FWD_COLOR),
                hovertemplate=f"{lbl}<br>DU: %{{x}}<br>Cotacao: %{{y:.4f}}<extra></extra>",
            ))

    fig.update_layout(
        **_base_layout("Dolar Forward Implicito (paridade coberta)", 400),
        xaxis=dict(title="Prazo (DU)", gridcolor=_GRID),
        yaxis=dict(title="R$/USD", tickformat=".4f", gridcolor=_GRID),
    )
    return fig


def chart_taxa_real(dap_contracts: list, delta_ipca_bps: float = 0.0,
                     legs: list[dict] = None) -> go.Figure:
    """Curva DAP (taxa real IPCA) antes/depois do choque."""
    from lib.calendar import default_liq_date
    from datetime import date

    fig = go.Figure()
    liq = default_liq_date(date.today())
    vertices = build_dap_vertices(dap_contracts, liq)
    if not vertices:
        fig.update_layout(**_base_layout("Taxa Real (DAP) — sem dados", 400))
        return fig

    smooth = flat_forward_curve(vertices, du_step=5)
    if not smooth:
        fig.update_layout(**_base_layout("Taxa Real (DAP) — sem dados", 400))
        return fig

    dus = [p[0] for p in smooth]
    rates_before = [p[1] for p in smooth]

    fig.add_trace(go.Scatter(
        x=dus, y=rates_before, mode="lines",
        name="DAP Antes",
        line=dict(color=_MUTED, width=1.5, dash="dash"),
        hovertemplate="DU: %{x}<br>Taxa real: %{y:.3f}%<extra>Antes</extra>",
    ))

    rates_after = [r + delta_ipca_bps / 100 for r in rates_before]
    fig.add_trace(go.Scatter(
        x=dus, y=rates_after, mode="lines",
        name="DAP Depois",
        line=dict(color=_DAP_COLOR, width=2),
        hovertemplate="DU: %{x}<br>Taxa real: %{y:.3f}%<extra>Depois</extra>",
    ))

    fig.add_trace(go.Scatter(
        x=dus + dus[::-1],
        y=rates_after + rates_before[::-1],
        fill="toself", fillcolor="rgba(210,153,34,0.06)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))

    vert_dus = [v[0] for v in vertices]
    vert_rates = [v[1] for v in vertices]
    fig.add_trace(go.Scatter(
        x=vert_dus, y=vert_rates, mode="markers",
        name="Vertices DAP",
        marker=dict(size=5, color=_DAP_COLOR, symbol="diamond"),
        hovertemplate="DU: %{x}<br>Taxa: %{y:.3f}%<extra>Vertice</extra>",
    ))

    if legs:
        ipca_legs = [l for l in legs if l["instrument"] in ("NTN-B", "DAP")]
        for l in ipca_legs:
            lbl = f"{_dir_label(l)} {l['instrument']} {l['parsed']['label']}"
            fig.add_trace(go.Scatter(
                x=[l["du"]], y=[l["tax_fin"]], mode="markers+text",
                name=lbl,
                marker=dict(size=10, color=_DAP_COLOR, symbol="circle"),
                text=[lbl], textposition="top center",
                textfont=dict(size=10, color=_DAP_COLOR),
                hovertemplate=f"{lbl}<br>DU: %{{x}}<br>Taxa: %{{y:.3f}}%<extra></extra>",
            ))

    fig.update_layout(
        **_base_layout("Taxa Real (DAP) — Cupom IPCA", 400),
        xaxis=dict(title="Prazo (DU)", gridcolor=_GRID),
        yaxis=dict(title="Taxa real (% a.a.)", tickformat=".2f", gridcolor=_GRID),
    )
    return fig


def chart_krd(flows: list) -> go.Figure:
    labels = [f.label for f in flows]
    krds = [f.krd for f in flows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=krds, name="KRD",
        marker_color=_BLUE,
        text=[f"{v:.3f}" for v in krds],
        textposition="outside", textfont=dict(size=10),
    ))
    fig.update_layout(
        **_base_layout("Key-Rate Duration por Fluxo", 300),
        xaxis=dict(title="Fluxo", gridcolor=_GRID),
        yaxis=dict(title="KRD (anos)", gridcolor=_GRID),
        showlegend=False,
    )
    return fig
