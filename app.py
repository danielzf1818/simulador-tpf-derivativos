"""Simulador TPF + Derivativos — Streamlit App."""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from typing import Optional

from lib.calendar import parse_ticker, du_entre, dc_entre, default_liq_date, MONTH_NAMES
from lib.market_data import (
    fetch_all as _fetch_all_market, get_tpf_vctos, find_di1_rate_for_date,
)
from lib.instruments import (
    INSTRUMENTS, pu, duration, dv01, key_rate_duration, cupom_cambial_implicito,
)
from lib.exposure import get_exposure, detect_strategy, analyze_risk_factors, suggest_hedge
from lib.scenarios import SCENARIOS, calc_scenario_delta, calc_leg_pnl
from lib.charts import (
    chart_curva_antes_depois, chart_pnl_barras,
    chart_pnl_consolidado, chart_pnl_por_perna, chart_krd,
    chart_cupom_cambial, chart_dol_forward, chart_taxa_real,
)

st.set_page_config(page_title="Simulador TPF + Derivativos", layout="wide")

# ============================================================
# Custom CSS
# ============================================================
st.markdown("""
<style>
.stApp { font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif; }
.block-container { padding-top: 1.5rem; max-width: 100%; }
header[data-testid="stHeader"] { background: #0d1117; }

div[data-testid="stMetric"] {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 6px 10px;
}
div[data-testid="stMetric"] label {
    color: #8b949e; font-size: 10px; line-height: 1.2;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 0.95rem; line-height: 1.3;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
    font-size: 10px;
}

.stTabs [data-baseweb="tab-list"] { gap: 0px; border-bottom: 1px solid #30363d; }
.stTabs [data-baseweb="tab"] { color: #8b949e; }
.stTabs [aria-selected="true"] { color: #e6edf3 !important; }

.sec-h {
    font-size: 14px; font-weight: 600; color: #e6edf3;
    margin: 20px 0 10px 0; padding-bottom: 6px;
    border-bottom: 1px solid #30363d;
}

.sim-card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; overflow: hidden; margin-bottom: 20px;
}
.sim-card-h {
    padding: 10px 14px; font-size: 13px; font-weight: 600;
    color: #e6edf3; border-bottom: 1px solid #30363d; background: #1c2128;
}

.sim-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.sim-tbl th {
    background: #1c2128; color: #8b949e; padding: 8px 12px;
    font-size: 10px; font-weight: 600; text-transform: uppercase;
    letter-spacing: .3px; border-bottom: 1px solid #30363d;
    text-align: left; white-space: nowrap;
}
.sim-tbl td {
    padding: 8px 12px; border-bottom: 1px solid #21262d;
    color: #e6edf3; white-space: nowrap;
}
.sim-tbl tr:last-child td { border-bottom: none; }

.mono { font-family: 'SF Mono','Fira Code',Consolas,monospace; font-size: 12px; }
.tc { text-align: center; }
.tr { text-align: right; }
.bold { font-weight: 600; }
.green { color: #3fb950; }
.red { color: #f85149; }
.orange { color: #d29922; }
.blue { color: #58a6ff; }
.muted { color: #8b949e; }
.sm { font-size: 10px; }

.av-wrap {
    border: 2px solid #58a6ff; border-radius: 8px;
    overflow: hidden; margin: 10px 0 20px 0;
}
.av-wrap .sim-tbl th {
    background: rgba(88,166,255,.08); color: #58a6ff;
    font-size: 12px; text-transform: none; letter-spacing: 0; padding: 10px 16px;
}
.av-wrap .sim-tbl td { padding: 10px 16px; font-size: 13px; }
.av-result td {
    background: rgba(88,166,255,.1) !important;
    border-top: 2px solid #58a6ff !important;
    font-weight: 700 !important; font-size: 16px !important;
    color: #58a6ff !important; text-align: center !important;
    padding: 14px 16px !important;
}

.cb {
    display: inline-block; width: 4px; height: 20px;
    border-radius: 2px; margin-right: 8px; vertical-align: middle;
}

.pill-exp {
    display: inline-block; background: rgba(248,81,73,.15);
    color: #f85149; padding: 2px 8px; border-radius: 10px;
    font-size: 10px; font-weight: 600;
}
.pill-hdg {
    display: inline-block; background: rgba(63,185,80,.15);
    color: #3fb950; padding: 2px 8px; border-radius: 10px;
    font-size: 10px; font-weight: 600;
}

.page-sub { color: #8b949e; font-size: 11px; margin-bottom: 10px; }

/* Prevent "Adicionar Perna" button from overlapping */
div[data-testid="stButton"] { margin-top: 8px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# Constants
# ============================================================
ALL_INSTRUMENTS = list(INSTRUMENTS.keys())
CORR_TYPES = ["Nenhuma", "% na taxa", "R$/contrato", "R$/titulo"]

# ============================================================
# Market Data Helpers
# ============================================================
_MONTH_TO_TICKER = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
_TICKER_TO_MONTH = {v: k for k, v in _MONTH_TO_TICKER.items()}


@st.cache_data(ttl=300, show_spinner="Buscando dados de mercado...")
def _cached_fetch_market():
    return _fetch_all_market()


def _date_to_ticker(date_str: str) -> str:
    parts = date_str.split("-")
    return f"{_MONTH_TO_TICKER[int(parts[1])]}{int(parts[0]) % 100:02d}"


def _available_tickers(instrument: str, snap) -> list[str]:
    if not snap:
        return []
    _src = {"DI1": snap.di1, "DOL": snap.dol, "FRC": snap.frc, "DAP": snap.dap, "DDI": snap.ddi}
    if instrument in _src:
        return [c["symb"][3:] for c in _src[instrument] if len(c["symb"]) > 3]
    if instrument in ("LTN", "NTN-F", "NTN-B", "LFT"):
        return [_date_to_ticker(d) for d in get_tpf_vctos(instrument)]
    return []


def _market_rate(instrument: str, ticker: str, snap) -> Optional[float]:
    if not snap or not ticker:
        return None
    ticker = ticker.upper().strip()
    for src_attr, prefix in [("di1", "DI1"), ("dol", "DOL"), ("frc", "FRC"), ("dap", "DAP"), ("ddi", "DDI")]:
        if instrument == prefix:
            for c in getattr(snap, src_attr):
                if c["symb"] == f"{prefix}{ticker}":
                    return c["last"] if c["last"] > 0 else c["ajuste"]
            return None
    if instrument in ("LTN", "NTN-F", "NTN-B", "LFT"):
        try:
            letter = ticker[0].upper()
            yr = int(ticker[1:])
            if yr < 100:
                yr += 2000
            month = _TICKER_TO_MONTH.get(letter)
            if not month:
                return None
            day = 15 if instrument == "NTN-B" else 1
            target = f"{yr}-{month:02d}-{day:02d}"
            rate = find_di1_rate_for_date(snap.di1, target)
            return rate if rate > 0 else None
        except (ValueError, IndexError):
            return None
    return None


PRESETS = {
    "Casada LTN+DI1": [
        {"instrument": "LTN", "ticker": "F32", "direction": "C", "quantity": 2000, "taxa": 13.7625, "corr_type": "% na taxa", "corr_value": 0.001},
        {"instrument": "DI1", "ticker": "F32", "direction": "C", "quantity": 20, "taxa": 13.650, "corr_type": "R$/contrato", "corr_value": 1.30},
    ],
    "Venda Casada LTN+DI1": [
        {"instrument": "LTN", "ticker": "F32", "direction": "V", "quantity": 2000, "taxa": 13.7625, "corr_type": "% na taxa", "corr_value": 0.001},
        {"instrument": "DI1", "ticker": "F32", "direction": "V", "quantity": 20, "taxa": 13.650, "corr_type": "R$/contrato", "corr_value": 1.30},
    ],
    "Casada NTN-F+DI1": [
        {"instrument": "NTN-F", "ticker": "F31", "direction": "C", "quantity": 2000, "taxa": 13.80, "corr_type": "% na taxa", "corr_value": 0.001},
        {"instrument": "DI1", "ticker": "F31", "direction": "C", "quantity": 20, "taxa": 13.65, "corr_type": "R$/contrato", "corr_value": 1.30},
    ],
    "Casada NTN-B+DAP": [
        {"instrument": "NTN-B", "ticker": "N29", "direction": "C", "quantity": 2000, "taxa": 7.50, "corr_type": "% na taxa", "corr_value": 0.001},
        {"instrument": "DAP", "ticker": "N29", "direction": "C", "quantity": 20, "taxa": 7.40, "corr_type": "R$/contrato", "corr_value": 1.30},
    ],
    "DOL+DI1 (cupom sint.)": [
        {"instrument": "DOL", "ticker": "K26", "direction": "C", "quantity": 10, "taxa": 4976.5, "corr_type": "Nenhuma", "corr_value": 0.0},
        {"instrument": "DI1", "ticker": "K26", "direction": "C", "quantity": 10, "taxa": 14.60, "corr_type": "R$/contrato", "corr_value": 1.30},
    ],
    "DI1+FRC (dol sint.)": [
        {"instrument": "DI1", "ticker": "F28", "direction": "C", "quantity": 20, "taxa": 14.60, "corr_type": "R$/contrato", "corr_value": 1.30},
        {"instrument": "FRC", "ticker": "F28", "direction": "V", "quantity": 20, "taxa": 5.06, "corr_type": "R$/contrato", "corr_value": 1.30},
    ],
    "FRC direcional": [
        {"instrument": "FRC", "ticker": "F28", "direction": "C", "quantity": 20, "taxa": 5.06, "corr_type": "R$/contrato", "corr_value": 1.30},
    ],
    "LTN direcional": [
        {"instrument": "LTN", "ticker": "F32", "direction": "C", "quantity": 2000, "taxa": 13.76, "corr_type": "% na taxa", "corr_value": 0.001},
    ],
}


# ============================================================
# State & Processing
# ============================================================

def init_state():
    if "legs" not in st.session_state:
        st.session_state.legs = [p.copy() for p in PRESETS["Casada LTN+DI1"]]
    if "data_neg" not in st.session_state:
        st.session_state.data_neg = date(2026, 4, 28)
    if "spot" not in st.session_state:
        st.session_state.spot = 4.9724


def process_legs():
    data_neg = st.session_state.data_neg
    results = []
    for leg in st.session_state.legs:
        info = INSTRUMENTS.get(leg["instrument"])
        if not info:
            continue
        parsed = parse_ticker(leg["instrument"], leg["ticker"])
        if not parsed:
            continue

        liq = leg.get("data_liq") or default_liq_date(data_neg)
        du = du_entre(liq, parsed["date"])
        dc = dc_entre(liq, parsed["date"])

        if info.type == "tpf" or info.conv == "price":
            side = "Ativo" if leg["direction"] == "C" else "Passivo"
        else:
            side = "Passivo" if leg["direction"] == "C" else "Ativo"

        if info.conv == "price":
            tax_dir = "Compra USD" if leg["direction"] == "C" else "Vende USD"
        elif info.type == "tpf":
            tax_dir = "Vende taxa" if leg["direction"] == "C" else "Compra taxa"
        else:
            tax_dir = "Compra taxa" if leg["direction"] == "C" else "Vende taxa"

        pu_val = pu(leg["instrument"], leg["taxa"], du, dc)
        dur = duration(leg["instrument"], leg["taxa"], du, dc)
        dv = dv01(leg["instrument"], leg["taxa"], du, dc, leg["quantity"])
        fin = pu_val * leg["quantity"]
        noc = leg["quantity"] * info.face
        exp = get_exposure(leg["instrument"], leg["direction"], leg["taxa"])

        tax_fin = leg["taxa"]
        corr_brl, corr_bps = 0.0, 0.0
        if leg["corr_type"] == "% na taxa" and info.conv != "price":
            tax_fin = (leg["taxa"] - leg["corr_value"]
                       if leg["direction"] == "C"
                       else leg["taxa"] + leg["corr_value"])
            corr_brl = abs(pu(leg["instrument"], tax_fin, du, dc) - pu_val) * leg["quantity"]
            corr_bps = leg["corr_value"] * 100
        elif leg["corr_type"] in ("R$/contrato", "R$/titulo"):
            corr_brl = leg["corr_value"] * leg["quantity"]
            corr_bps = corr_brl / dv.total if dv.total > 0 else 0

        results.append({
            **leg, "info": info, "parsed": parsed, "du": du, "dc": dc,
            "liq": liq,
            "side": side, "tax_dir": tax_dir, "tax_fin": tax_fin,
            "pu": pu_val, "fin": fin, "noc": noc,
            "d_mac": dur.macaulay, "d_mod": dur.modificada,
            "dv01_unit": dv.unit, "dv01_total": dv.total,
            "corr_brl": corr_brl, "corr_bps": corr_bps, "exp": exp,
        })
    return results


# ============================================================
# HTML Rendering Helpers
# ============================================================

def _extract_factor(s):
    """'Pre 13.763%' -> 'Pre', 'CDI' -> 'CDI', '--' -> None."""
    if not s or s in ("--", "\u2014"):
        return None
    return s.split()[0]


def _compute_cancel_colors(av_rows):
    """Assign cancel bar colors to rows where factors cancel across ativo/passivo."""
    pair_colors = ["#d29922", "#bc8cff", "#f778ba", "#58a6ff"]
    ativo_map = {}
    passivo_map = {}
    for i, row in enumerate(av_rows):
        af = _extract_factor(row.get("ativo"))
        pf = _extract_factor(row.get("passivo"))
        if af:
            ativo_map.setdefault(af, set()).add(i)
        if pf:
            passivo_map.setdefault(pf, set()).add(i)

    row_colors = {}
    ci = 0
    for factor in sorted(set(ativo_map) & set(passivo_map)):
        color = pair_colors[ci % len(pair_colors)]
        ci += 1
        for idx in ativo_map[factor]:
            row_colors[idx] = color
        for idx in passivo_map[factor]:
            row_colors[idx] = color
    return row_colors


def render_av_table_html(valid, strat, total_corr_bps):
    av_rows = []
    for l in valid:
        av_rows.append({
            "direction": l["direction"],
            "instrument": l["instrument"],
            "vcto": l["parsed"]["label"],
            "ativo": l["exp"]["ativo"],
            "passivo": l["exp"]["passivo"],
        })

    result_text = ""
    if strat["type"] == "casada":
        allin = strat["spread"] - total_corr_bps
        result_text = f"{strat['bmk']} {allin:+.2f} bps"
    elif strat["type"] == "cupom_sint":
        result_text = f"Cupom cambial {strat['cupom']:.2f}% a.a."
    else:
        result_text = strat["result"]

    cancel_colors = _compute_cancel_colors(av_rows)

    html = '<div class="av-wrap"><table class="sim-tbl">'
    html += '<tr><th></th><th>Instrumento</th><th class="tc">Ativo</th><th class="tc">Passivo</th><th class="tc">Vcto</th></tr>'

    for i, row in enumerate(av_rows):
        is_buy = row["direction"] == "C"
        dir_label = "Compra" if is_buy else "Venda"
        dir_color = "#3fb950" if is_buy else "#f85149"

        bar_html = ""
        if i in cancel_colors:
            bar_html = f'<span class="cb" style="background:{cancel_colors[i]}"></span>'

        html += f'<tr><td>{bar_html}<span style="color:{dir_color};font-weight:600">{dir_label}</span></td>'
        html += f'<td class="bold">{row["instrument"]}</td>'
        html += f'<td class="tc mono">{row["ativo"]}</td>'
        html += f'<td class="tc mono">{row["passivo"]}</td>'
        html += f'<td class="tc mono muted">{row["vcto"]}</td></tr>'

    if result_text:
        html += f'<tr class="av-result"><td colspan="5">{result_text}</td></tr>'

    html += '</table></div>'
    return html


def render_risk_html(risk_factors):
    if not risk_factors:
        return ""

    html = '<div class="sim-card"><div class="sim-card-h">Fatores de Risco</div>'
    html += '<table class="sim-tbl"><tr><th>Fator</th><th class="tc">Status</th><th>Descricao</th></tr>'

    for f in risk_factors:
        pill_class = "pill-exp" if f["exposto"] else "pill-hdg"
        pill_text = "EXPOSTO" if f["exposto"] else "HEDGEADO"
        html += f'<tr><td class="bold">{f["fator"]}</td>'
        html += f'<td class="tc"><span class="{pill_class}">{pill_text}</span></td>'
        html += f'<td class="muted sm">{f["desc"]}</td></tr>'

    html += '</table></div>'
    return html


def render_mtm_html(valid, scenario_key,
                    delta_fx_pct: float = 0.0,
                    delta_ipca_bps: float = 0.0,
                    delta_cupom_bps: float = 0.0):
    rate_legs = [l for l in valid if l["info"].conv != "price"]
    if not rate_legs and not any(l["info"].conv == "price" for l in valid):
        return ""
    du_min = min(l["du"] for l in rate_legs) if rate_legs else 0
    du_max = max(l["du"] for l in rate_legs) if rate_legs else 1

    steps = [-20, -15, -10, -5, -2, -1, 0, 1, 2, 5, 10, 15, 20]

    leg_labels = [f"{l['instrument']} {l['parsed']['label']}" for l in valid]
    html = '<div class="sim-card"><div class="sim-card-h">Tabela de Cenarios MtM (per-leg P&L)</div>'
    html += '<div style="overflow-x:auto"><table class="sim-tbl"><tr><th class="tc">Delta (bps)</th>'
    for lbl in leg_labels:
        html += f'<th class="tr">{lbl}</th>'
    html += '<th class="tr bold">Total</th></tr>'

    for m in steps:
        row_total = 0.0
        cells = []
        for l in valid:
            if l["info"].conv == "price":
                delta = 0.0
            else:
                delta = calc_scenario_delta(l["du"], du_min, du_max, scenario_key, m)
            pnl = calc_leg_pnl(l, delta,
                               delta_fx_pct=delta_fx_pct,
                               delta_ipca_bps=delta_ipca_bps,
                               delta_cupom_bps=delta_cupom_bps)
            row_total += pnl
            cc = " green" if pnl > 1 else (" red" if pnl < -1 else "")
            cells.append(f'<td class="tr mono{cc}">R$ {pnl:+,.0f}</td>')

        tot_cc = " green" if row_total > 1 else (" red" if row_total < -1 else "")
        bg = ' style="background:#1c2128"' if m == 0 else ''
        html += f'<tr{bg}><td class="tc mono">{m:+d}</td>'
        html += ''.join(cells)
        html += f'<td class="tr mono bold{tot_cc}">R$ {row_total:+,.0f}</td></tr>'

    html += '</table></div></div>'
    return html


# ============================================================
# Formulas Tab
# ============================================================

def render_formulas():
    st.caption("Todas as formulas usadas no simulador, organizadas por tema. Convencoes do mercado brasileiro.")

    st.header("Titulos Publicos (TPF)")

    st.subheader("LTN -- Zero-Coupon Prefixado")
    st.latex(r"PU = \frac{1.000}{(1 + taxa)^{DU/252}}")
    st.caption("Convencao: exponencial, base 252 DU. Truncamento ANBIMA: T-6.")

    st.subheader("NTN-F -- Prefixado com Cupom Semestral")
    st.latex(r"Cupom_{sem} = (1{,}10)^{0{,}5} - 1 = 4{,}880885\%")
    st.latex(r"PU = \sum_{i=1}^{n} \frac{Cupom \times VN}{(1 + TIR)^{DU_i/252}} + \frac{VN}{(1 + TIR)^{DU_n/252}}")
    st.caption("Cupom edital: 10% a.a. Fluxos semestrais arredondados 9 casas (A-9). PU truncado 6 casas (T-6).")

    st.subheader("NTN-B -- IPCA+ com Cupom Semestral")
    st.latex(r"Cupom_{sem} = (1{,}06)^{0{,}5} - 1 = 2{,}956301\%")
    st.latex(r"Cotacao(\%) = \sum_{i=1}^{n} \frac{Cupom\%}{(1 + TIR)^{DU_i/252}} + \frac{100}{(1 + TIR)^{DU_n/252}}")
    st.latex(r"PU = \frac{Cotacao}{100} \times VNA")
    st.caption("Cotacao truncada 4 casas (T-4). VNA truncado 6 casas (T-6). PU truncado 6 casas (T-6).")

    st.subheader("LFT -- Tesouro Selic")
    st.latex(r"Cotacao(\%) = \frac{100}{(1 + Rentabilidade/100)^{DU/252}}")
    st.latex(r"PU = \frac{Cotacao}{100} \times VNA_{Selic}")

    st.divider()
    st.header("Derivativos de Taxa de Juros")

    st.subheader("DI1 -- Futuro de DI")
    st.latex(r"PU = \frac{100.000}{(1 + taxa)^{DU/252}}")
    st.caption("Convencao: exponencial, base 252 DU. Face R$ 100.000. Vencimento: 1o DU do mes.")

    st.subheader("DAP -- Futuro de Cupom de IPCA")
    st.latex(r"PU = \frac{100.000}{(1 + cupom_{IPCA})^{DU/252}}")
    st.caption("Convencao: exponencial, base 252 DU. Taxa real.")

    st.divider()
    st.header("Derivativos de Cambio")

    st.subheader("DOL -- Dolar Futuro")
    st.latex(r"AJ = (PA - PO) \times qtd \times 50")
    st.caption("Cotacao em R$ por USD 1.000. Multiplicador: 50 (cada ponto = R$ 50/contrato). Face: USD 50.000.")

    st.subheader("DDI -- Cupom Cambial Sujo")
    st.latex(r"PU = \frac{100.000}{1 + taxa \times \frac{DC}{360}}")
    st.caption("Convencao: linear, base 360 DC. Face: USD 100.000 (efetivo USD 50.000, pois cada ponto = USD 0,50).")

    st.subheader("FRC -- FRA de Cupom Cambial (Limpo)")
    st.latex(r"PU = \frac{50.000}{1 + cupom \times \frac{DC}{360}}")
    st.caption("Convencao: linear, base 360 DC. Face: USD 50.000. Negocia cupom cambial limpo (sem efeito PTAX).")

    st.subheader("Cupom Cambial Implicito (DOL + DI1)")
    st.latex(r"cupom = \left[\frac{Spot \times 1000}{DOL} \times (1 + DI)^{DU/252} - 1\right] \times \frac{360}{DC} \times 100")
    st.caption("Numerador: fator de juros em reais (exp252). Denominador normalizado pelo DOL futuro. Resultado em % a.a. linear 360.")

    st.divider()
    st.header("Duration e Risco")

    st.subheader("Duration de Macaulay")
    st.latex(r"D_{mac} = \frac{\sum_{i=1}^{n} t_i \times PV_i}{\sum_{i=1}^{n} PV_i}")
    st.caption("t_i = DU_i / 252 (em anos). PV_i = valor presente do fluxo i. Para zero-coupon: D_mac = DU/252.")

    st.subheader("Duration Modificada")
    st.latex(r"D_{mod} = \frac{D_{mac}}{1 + taxa}")
    st.caption("Sensibilidade percentual do preco a variacao de 1 unidade na taxa.")

    st.subheader("DV01 (Dollar Value of 01)")
    st.latex(r"DV01 = D_{mod} \times PU \times 0{,}0001")
    st.caption("Variacao absoluta do valor para shift de 1 bp. Para DOL: DV01 = multiplicador (R$ 50/ponto).")

    st.subheader("Convexidade")
    st.latex(r"C = \frac{1}{PU} \sum_{i=1}^{n} \frac{t_i(t_i + \Delta t) \times FC_i}{(1+y)^{t_i+2}}")

    st.subheader("Aproximacao de Preco (Taylor 2a ordem)")
    st.latex(r"\frac{\Delta P}{P} \approx -D_{mod} \times \Delta y + \frac{1}{2} C \times (\Delta y)^2")

    st.divider()
    st.header("Conversoes de Taxa")

    st.subheader("CDI + Spread vs Pre")
    st.latex(r"(1 + CDI) \times (1 + Spread) = (1 + Pre)")
    st.latex(r"Spread = \frac{1 + Pre}{1 + CDI} - 1")
    st.caption("NUNCA somar CDI + Spread diretamente. A composicao eh multiplicativa.")

    st.subheader("Fisher (Nominal vs Real)")
    st.latex(r"(1 + nominal) = (1 + real) \times (1 + inflacao)")
    st.latex(r"inflacao_{implicita} = \frac{1 + DI}{1 + DAP} - 1")

    st.subheader("Linear 360 vs Exponencial 252")
    st.latex(r"exp_{252} = \left(1 + lin_{360} \times \frac{DC}{360}\right)^{252/DU} - 1")
    st.latex(r"lin_{360} = \left[(1 + exp_{252})^{DU/252} - 1\right] \times \frac{360}{DC}")

    st.subheader("Over vs Anual")
    st.latex(r"anual = (1 + over)^{252} - 1")
    st.latex(r"over = (1 + anual)^{1/252} - 1")

    st.divider()
    st.header("Datas e Calendario")

    st.subheader("Dias Uteis (DU)")
    st.latex(r"DU = NETWORKDAYS(d_1, d_2, feriados) - 1")
    st.caption("Calendario ANBIMA. Exclui sabados, domingos e feriados nacionais. Subtrair 1 eh obrigatorio.")

    st.subheader("Fracao de Ano")
    st.latex(r"t = \frac{DU}{252} \quad \text{(exponencial)} \qquad t = \frac{DC}{360} \quad \text{(linear)}")

    st.subheader("FRA (Forward Rate Agreement)")
    st.latex(r"FRA_{DI} = \left[\frac{(1+r_L)^{DU_L/252}}{(1+r_C)^{DU_C/252}}\right]^{252/(DU_L-DU_C)} - 1")
    st.latex(r"FRA_{cupom} = \left[\frac{1+cc_L \times DC_L/360}{1+cc_C \times DC_C/360} - 1\right] \times \frac{360}{DC_L - DC_C}")

    st.subheader("Interpolacao Flat Forward (B3 V14)")
    st.latex(r"fwd = \left[\frac{(1+r_2)^{DU_2/252}}{(1+r_1)^{DU_1/252}}\right]^{252/(DU_2-DU_1)} - 1")
    st.latex(r"r_{alvo} = \left[(1+r_1)^{DU_1/252} \times (1+fwd)^{(DU_{alvo}-DU_1)/252}\right]^{252/DU_{alvo}} - 1")
    st.caption("Premissa: taxa forward constante entre vertices adjacentes. Manual de Curvas B3 V14.")

    st.divider()
    st.header("Cenarios de Curva")

    st.caption("t = posicao normalizada na curva (-1 = curto, +1 = longo)")

    st.subheader("Paralelo (Shift)")
    st.latex(r"\Delta_i = \pm magnitude")

    st.subheader("Steepener / Flattener (Inclinacao)")
    st.latex(r"\Delta_i = magnitude \times t_i")
    st.caption("Steepener: curtos caem, longos sobem. Flattener: inverso.")

    st.subheader("Butterfly (Curvatura)")
    st.latex(r"\Delta_i = magnitude \times (1 - t_i^2) - \frac{magnitude}{2}")
    st.caption("Barriga recebe choque maximo, pontas recebem minimo.")

    st.subheader("Paridade Coberta de Juros")
    st.latex(r"(1 + pre)^{DU/252} = \frac{Futuro}{Spot} \times (1 + cupom \times \frac{DC}{360})")


# ============================================================
# MAIN APP
# ============================================================
init_state()

# --- Title + Config row ---
c_title, _, c_date, c_spot = st.columns([3, 2, 1, 1])
with c_title:
    st.markdown("## Simulador TPF + Derivativos")
    st.markdown(
        '<p class="page-sub">TPF (LTN, NTN-F, NTN-B, LFT) + Derivativos (DI1, DAP, DOL, DDI, FRC)</p>',
        unsafe_allow_html=True)
with c_date:
    st.session_state.data_neg = st.date_input(
        "Data neg.", st.session_state.data_neg, format="DD/MM/YYYY")
with c_spot:
    st.session_state.spot = st.number_input(
        "Spot USD (R$/USD)", value=st.session_state.spot,
        format="%.4f", step=0.0001)

# --- Market Data ---
def _on_fetch_market():
    """on_click callback — runs BEFORE widgets render, avoiding key conflicts."""
    _cached_fetch_market.clear()
    _snap = _cached_fetch_market()
    st.session_state.market_data = _snap
    for _lg in st.session_state.legs:
        _r = _market_rate(_lg["instrument"], _lg["ticker"], _snap)
        if _r is not None:
            _lg["taxa"] = _r
        _lg["_prev_inst"] = _lg["instrument"]
        _lg["_prev_tick"] = _lg["ticker"]
    if _snap.spot_usd > 0:
        st.session_state.spot = round(_snap.spot_usd, 4)
    elif _snap.ptax > 0:
        st.session_state.spot = _snap.ptax

if "market_data" not in st.session_state:
    _on_fetch_market()

_mkt_col, _ = st.columns([1.5, 4])
with _mkt_col:
    st.button("Atualizar Dados de Mercado", type="primary",
              use_container_width=True, on_click=_on_fetch_market)

snap = st.session_state.get("market_data")

if snap and snap.timestamp:
    _mc1, _mc2, _mc3, _mc4 = st.columns(4)
    _mc1.metric("CDI", f"{snap.cdi_aa:.2f}%")
    _mc2.metric("PTAX", f"{snap.ptax:.4f}")
    _mc3.metric("Spot USD", f"~{snap.spot_usd:.2f}" if snap.spot_usd > 0 else "--")
    _mc4.metric("Atualizado", snap.timestamp)

# --- Tabs ---
st.markdown("""<style>
.stTabs [data-baseweb="tab-list"] {gap: 24px;}
.stTabs [data-baseweb="tab"] {font-size: 16px; padding: 8px 20px;}
</style>""", unsafe_allow_html=True)
tab_sim, tab_mkt, tab_form = st.tabs(["Simulador", "Dados de Mercado", "Formulas"])

with tab_sim:
    # ========== PRESETS ==========
    preset_names = list(PRESETS.keys())
    preset_cols = st.columns(len(preset_names))
    for col, name in zip(preset_cols, preset_names):
        with col:
            if st.button(name, use_container_width=True, key=f"pr_{name}"):
                st.session_state.legs = [p.copy() for p in PRESETS[name]]
                st.rerun()

    # ========== LEG INPUTS ==========
    st.markdown('<div class="sec-h">Pernas da Operacao</div>', unsafe_allow_html=True)

    legs_to_remove = []
    default_liq = default_liq_date(st.session_state.data_neg)

    for i, leg in enumerate(st.session_state.legs):
        info = INSTRUMENTS.get(leg["instrument"], INSTRUMENTS["LTN"])
        cols = st.columns([1.2, 0.7, 0.6, 0.8, 1.0, 1.0, 0.7, 0.6])
        vis = "visible" if i == 0 else "collapsed"

        with cols[0]:
            _new_inst = st.selectbox(
                "Instrumento", ALL_INSTRUMENTS,
                index=ALL_INSTRUMENTS.index(leg["instrument"]),
                key=f"inst_{i}", label_visibility=vis)
            _inst_chg = _new_inst != leg.get("_prev_inst", leg["instrument"])
            leg["instrument"] = _new_inst

        _avail = _available_tickers(leg["instrument"], snap) if snap else []
        if _inst_chg and _avail and leg["ticker"].upper().strip() not in _avail:
            leg["ticker"] = _avail[0]
            if f"tick_{i}" in st.session_state:
                del st.session_state[f"tick_{i}"]

        with cols[1]:
            if _avail:
                _cur = leg["ticker"].upper().strip()
                if _cur not in _avail:
                    _avail = [_cur] + _avail
                if f"tick_{i}" in st.session_state and st.session_state[f"tick_{i}"] not in _avail:
                    del st.session_state[f"tick_{i}"]
                leg["ticker"] = st.selectbox(
                    "Ticker", _avail, index=_avail.index(_cur),
                    key=f"tick_{i}", label_visibility=vis)
            else:
                leg["ticker"] = st.text_input(
                    "Ticker", leg["ticker"],
                    key=f"tick_{i}", label_visibility=vis)

        _tick_chg = leg["ticker"] != leg.get("_prev_tick", leg["ticker"])
        if snap and (_inst_chg or _tick_chg) and leg.get("_prev_inst") is not None:
            _rate = _market_rate(leg["instrument"], leg["ticker"], snap)
            if _rate is not None:
                leg["taxa"] = _rate
        leg["_prev_inst"] = leg["instrument"]
        leg["_prev_tick"] = leg["ticker"]

        with cols[2]:
            leg["direction"] = st.selectbox(
                "C/V", ["C", "V"],
                index=0 if leg["direction"] == "C" else 1,
                key=f"dir_{i}",
                format_func=lambda x: "Compra" if x == "C" else "Venda",
                label_visibility=vis)
        with cols[3]:
            leg["quantity"] = st.number_input(
                "Qtd", value=leg["quantity"], step=1,
                key=f"qty_{i}", label_visibility=vis)
        with cols[4]:
            price_mode = INSTRUMENTS.get(
                leg["instrument"], INSTRUMENTS["LTN"]).conv == "price"
            label = "Cotacao" if price_mode else "Taxa (%)"
            leg["taxa"] = st.number_input(
                label, value=leg["taxa"], format="%.4f", step=0.005,
                key=f"tx_{i}", label_visibility=vis)
        with cols[5]:
            liq_val = leg.get("data_liq") or default_liq
            leg["data_liq"] = st.date_input(
                "Liquidacao", value=liq_val,
                format="DD/MM/YYYY",
                key=f"liq_{i}", label_visibility=vis)
        with cols[6]:
            leg["corr_type"] = st.selectbox(
                "Corretagem", CORR_TYPES,
                index=CORR_TYPES.index(leg.get("corr_type", "Nenhuma")),
                key=f"ct_{i}", label_visibility=vis)
        with cols[7]:
            _sub = st.columns([3, 1])
            with _sub[0]:
                leg["corr_value"] = st.number_input(
                    "Valor", value=leg.get("corr_value", 0.0),
                    format="%.3f", step=0.001,
                    key=f"cv_{i}", label_visibility=vis)
            with _sub[1]:
                if len(st.session_state.legs) > 1:
                    st.markdown(
                        f'<div style="padding-top:{"27" if i == 0 else "0"}px">'
                        f'</div>', unsafe_allow_html=True)
                    if st.button("✕", key=f"rm_{i}"):
                        legs_to_remove.append(i)

    for idx in sorted(legs_to_remove, reverse=True):
        st.session_state.legs.pop(idx)
    if legs_to_remove:
        st.rerun()

    if st.button("+ Adicionar Perna", type="secondary"):
        st.session_state.legs.append({
            "instrument": "LTN", "ticker": "F32", "direction": "C",
            "quantity": 2000, "taxa": 13.76,
            "corr_type": "Nenhuma", "corr_value": 0.0,
        })
        st.rerun()

    st.divider()

    # ========== PROCESS ==========
    valid = process_legs()
    if not valid:
        st.warning("Adicione ao menos uma perna valida.")
        st.stop()

    strat = detect_strategy(valid, st.session_state.spot)
    total_corr = sum(l["corr_brl"] for l in valid)
    total_corr_bps = sum(l["corr_bps"] for l in valid if l["info"].conv != "price")

    # ========== SUMMARY METRICS ==========
    st.divider()
    if strat["type"] == "casada":
        allin = strat["spread"] - total_corr_bps
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Spread All-in", f"{allin:.2f} bps")
        c2.metric("Retorno Equivalente", f"{strat['bmk']} {allin:+.2f} bps")
        tpf_noc = next((l["noc"] for l in valid if l["info"].type == "tpf"), 0)
        c3.metric("Nocional", f"R$ {tpf_noc/1e6:.1f}M")
        c4.metric("Corretagem Total", f"R$ {total_corr:.0f}")
    elif strat["type"] == "cupom_sint":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cupom Cambial Implicito", f"{strat['cupom']:.2f}% a.a.")
        c2.metric("DOL Futuro", f"{strat['dol']['taxa']:.1f}")
        c3.metric("Spot", f"{st.session_state.spot:.4f}")
        c4.metric("DI1", f"{strat['di']['taxa']:.3f}%")
    elif strat["type"] in ("dol_sint", "dol_sint_ddi"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Dolar Forward Sintetico", f"~{strat.get('fwd', 0):.2f}" if strat.get("fwd") else strat["result"][:30])
        c2.metric("DI1", f"{strat['di']['taxa']:.3f}%")
        frc_or_ddi = strat.get("frc") or strat.get("ddi")
        if frc_or_ddi:
            c3.metric(frc_or_ddi["instrument"], f"{frc_or_ddi['taxa']:.3f}%")
        c4.metric("Spot", f"{st.session_state.spot:.4f}")
    elif strat["type"] == "single":
        r = valid[0]
        c1, c2, c3, c4 = st.columns(4)
        if r["info"].conv == "price":
            c1.metric("Cotacao", f"{r['taxa']:.1f}")
        else:
            c1.metric("Taxa", f"{r['taxa']:.3f}%")
            c2.metric("PU", f"{r['pu']:.2f}")
        c3.metric(
            "Financeiro",
            f"R$ {r['fin']:,.0f}" if r["info"].conv != "price" else "--")
        c4.metric("DV01 Total", f"R$ {r['dv01_total']:.0f}")
    else:
        total_dv01 = sum(l["dv01_total"] for l in valid)
        total_fin = sum(l["fin"] for l in valid if l["info"].conv != "price")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Estrategia", strat["result"][:40])
        c2.metric("Financeiro Total", f"R$ {total_fin:,.0f}")
        c3.metric("DV01 Total", f"R$ {total_dv01:.0f}")
        c4.metric("Corretagem Total", f"R$ {total_corr:.0f}")

    # ========== ATIVO VS PASSIVO ==========
    st.markdown('<div class="sec-h">Ativo vs Passivo</div>', unsafe_allow_html=True)
    st.markdown(render_av_table_html(valid, strat, total_corr_bps), unsafe_allow_html=True)

    # ========== RISK FACTORS ==========
    risk_factors = analyze_risk_factors(valid, strat)
    if risk_factors:
        st.markdown(render_risk_html(risk_factors), unsafe_allow_html=True)

    # ========== DETAILS ==========
    st.divider()
    st.markdown('<div class="sec-h">Detalhes das Pernas</div>', unsafe_allow_html=True)
    det_data = []
    for l in valid:
        is_price = l["info"].conv == "price"
        row = {
            "Instr.": l["instrument"],
            "Dir.": "Compra" if l["direction"] == "C" else "Venda",
            "Lado": l["side"],
            "Vcto": l["parsed"]["full"],
            "Liq": l["liq"].strftime("%d/%m/%Y"),
            "DU": l["du"],
            "DC": l["dc"],
            "Taxa": f"{l['taxa']:.1f}" if is_price else f"{l['taxa']:.4f}%",
            "Final": f"{l['tax_fin']:.1f}" if is_price else f"{l['tax_fin']:.4f}%",
            "PU": f"{l['pu']:.1f}" if is_price else f"{l['pu']:.2f}",
            "Financeiro": "--" if is_price else f"R$ {l['fin']:,.0f}",
            "D.Mac": f"{l['d_mac']:.2f}",
            "D.Mod": f"{l['d_mod']:.2f}",
            "DV01/un": f"{l['dv01_unit']:.2f}",
            "DV01 Tot": f"{l['dv01_total']:.0f}",
            "Corr R$": f"{l['corr_brl']:.2f}",
            "Corr bps": f"{l['corr_bps']:.2f}",
        }
        det_data.append(row)
    st.dataframe(
        pd.DataFrame(det_data), use_container_width=True, hide_index=True)

    # ========== SPREAD & COSTS (casada only) ==========
    if strat["type"] == "casada":
        allin = strat["spread"] - total_corr_bps
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown('<div class="sec-h">Spread All-in</div>', unsafe_allow_html=True)
            spread_rows = [
                {"Item": "Spread bruto", "Valor": f"{strat['spread']:.2f} bps"},
            ]
            for l in valid:
                if l["info"].conv != "price":
                    spread_rows.append({
                        "Item": f"Corretagem {l['instrument']}",
                        "Valor": f"-{l['corr_bps']:.2f} bps",
                    })
            spread_rows.append({
                "Item": "Spread all-in", "Valor": f"{allin:.2f} bps",
            })
            st.dataframe(
                pd.DataFrame(spread_rows),
                use_container_width=True, hide_index=True)
        with sc2:
            st.markdown('<div class="sec-h">Custos</div>', unsafe_allow_html=True)
            cost_rows = []
            for l in valid:
                cost_rows.append({
                    "Item": f"Corretagem {l['instrument']} ({l['parsed']['label']})",
                    "R$": f"{l['corr_brl']:.2f}",
                    "bps": f"-{l['corr_bps']:.2f}",
                })
            cost_rows.append({
                "Item": "Total",
                "R$": f"R$ {total_corr:.2f}",
                "bps": f"-{total_corr_bps:.2f}",
            })
            st.dataframe(
                pd.DataFrame(cost_rows),
                use_container_width=True, hide_index=True)

    # ========== KRD & HEDGE ==========
    tpf_cupom = next(
        (l for l in valid if INSTRUMENTS[l["instrument"]].cup_sem > 0), None)
    if tpf_cupom:
        st.divider()
        flows = key_rate_duration(
            tpf_cupom["instrument"], tpf_cupom["taxa"], tpf_cupom["du"])
        if flows:
            st.markdown(
                f'<div class="sec-h">Key-Rate Duration -- {tpf_cupom["instrument"]} '
                f'{tpf_cupom["parsed"]["label"]}</div>',
                unsafe_allow_html=True)
            kc1, kc2 = st.columns([2, 1])
            with kc1:
                st.plotly_chart(chart_krd(flows), use_container_width=True)
            with kc2:
                krd_rows = [{
                    "Fluxo": f.label, "DU": str(f.du),
                    "VP": f"{f.pv:.2f}",
                    "Peso": f"{f.peso*100:.1f}%",
                    "KRD": f"{f.krd:.4f}",
                } for f in flows]
                krd_rows.append({
                    "Fluxo": "Total", "DU": "",
                    "VP": "", "Peso": "100%",
                    "KRD": f"{sum(f.krd for f in flows):.4f}",
                })
                st.dataframe(
                    pd.DataFrame(krd_rows),
                    use_container_width=True, hide_index=True)

        hedge = suggest_hedge(valid)
        if hedge:
            st.markdown('<div class="sec-h">Sugestao de Hedge</div>', unsafe_allow_html=True)
            di_leg = next(
                (l for l in valid if l["instrument"] in ("DI1", "DAP")), None)
            hc1, hc2, hc3 = st.columns(3)
            hc1.metric(
                f"DV01 {hedge['tpf']['instrument']}",
                f"R$ {hedge['tpf']['dv01_total']:.0f}")
            if di_leg:
                hc2.metric(
                    f"DV01 {di_leg['instrument']} ({di_leg['quantity']} contr.)",
                    f"R$ {di_leg['dv01_total']:.0f}")
            residual = hedge["dv01_residual"]
            hc3.metric(
                "DV01 Residual", f"R$ {residual:.0f}",
                delta="OK" if abs(residual) < 10 else "Desbalanceado")
            st.caption(
                f"Ideal no vcto final (~{hedge['du_maturity']} DU): "
                f"{hedge['n_at_maturity']} contratos | "
                f"Na duration (~{hedge['du_duration']} DU): "
                f"{hedge['n_at_duration']} contratos")

    # ========== SCENARIOS ==========
    rate_legs = [l for l in valid if l["info"].conv != "price"]
    has_dol_leg = any(l["instrument"] == "DOL" for l in valid)
    has_ntnb_or_dap = any(l["instrument"] in ("NTN-B", "DAP") for l in valid)
    has_cupom_leg = any(l["instrument"] in ("DDI", "FRC") for l in valid)
    has_dol_di_combo = has_dol_leg and any(l["instrument"] == "DI1" for l in valid)

    if rate_legs or has_dol_leg:
        st.divider()
        st.markdown('<div class="sec-h">Cenarios de Curva de Juros</div>', unsafe_allow_html=True)

        scenario_names = {k: v.name for k, v in SCENARIOS.items()}
        scenario_key = st.radio(
            "Cenario", list(scenario_names.keys()),
            format_func=lambda k: scenario_names[k],
            horizontal=True, key="sc_radio")

        sc = SCENARIOS[scenario_key]
        st.caption(sc.desc)

        is_dol_sint = strat["type"] in ("dol_sint", "dol_sint_ddi")
        show_fx = has_dol_leg
        show_ipca = has_ntnb_or_dap
        show_cupom = has_cupom_leg or has_dol_di_combo
        show_multi = show_fx or show_ipca or show_cupom

        delta_fx_pct = 0.0
        delta_ipca_bps = 0.0
        delta_cupom_bps = 0.0

        _chart_col, _slider_col = st.columns([3, 1])

        with _slider_col:
            st.markdown('<p style="font-size:12px;color:#8b949e;margin-bottom:4px">Choques</p>',
                        unsafe_allow_html=True)
            if scenario_key == "custom":
                custom_p = st.slider("Paralelo", -30, 30, 0, key="cp")
                custom_i = st.slider("Inclinacao", -30, 30, 0, key="ci")
                custom_c = st.slider("Curvatura", -30, 30, 0, key="cc")
                sc.parallel = custom_p
                sc.slope = custom_i
                sc.curvature = custom_c
                magnitude = 0
            else:
                magnitude = st.slider("Pre (bps)", -50, 50, 10, key="sc_mag")

            if show_fx:
                delta_fx_pct = st.slider(
                    "Cambio (%)", -10.0, 10.0, 0.0, 0.5, key="mf_fx")
            if show_ipca:
                delta_ipca_bps = st.slider(
                    "IPCA (bps)", -50, 50, 0, key="mf_ipca")
            if show_cupom:
                delta_cupom_bps = st.slider(
                    "Cup.Cambial (bps)", -50, 50, 0, key="mf_cupom")

            if is_dol_sint:
                st.caption("Dol sintetico: mova Pre e Cup.Cambial para simular cenarios FX.")

        with _chart_col:
            _tab_names = ["Curva Pre"]
            if show_cupom:
                _tab_names.append("Cupom Cambial")
            if show_fx or is_dol_sint or strat["type"] == "cupom_sint":
                _tab_names.append("Dolar Forward")
            if show_ipca:
                _tab_names.append("Taxa Real")

            if len(_tab_names) == 1:
                st.plotly_chart(
                    chart_curva_antes_depois(valid, scenario_key, magnitude,
                                             di1_curve=snap.di1 if snap else None,
                                             dap_curve=snap.dap if snap else None),
                    use_container_width=True)
            else:
                _chart_tabs = st.tabs(_tab_names)
                _cti = 0
                with _chart_tabs[_cti]:
                    st.plotly_chart(
                        chart_curva_antes_depois(valid, scenario_key, magnitude,
                                                 di1_curve=snap.di1 if snap else None,
                                                 dap_curve=snap.dap if snap else None),
                        use_container_width=True)
                _cti += 1
                if show_cupom:
                    with _chart_tabs[_cti]:
                        st.plotly_chart(
                            chart_cupom_cambial(
                                snap.frc if snap else [],
                                delta_cupom_bps=delta_cupom_bps,
                                legs=valid),
                            use_container_width=True)
                    _cti += 1
                if show_fx or is_dol_sint or strat["type"] == "cupom_sint":
                    with _chart_tabs[_cti]:
                        st.plotly_chart(
                            chart_dol_forward(
                                snap.di1 if snap else [],
                                snap.frc if snap else [],
                                spot=st.session_state.spot,
                                delta_pre_bps=magnitude,
                                delta_cupom_bps=delta_cupom_bps,
                                delta_fx_pct=delta_fx_pct,
                                legs=valid),
                            use_container_width=True)
                    _cti += 1
                if show_ipca:
                    with _chart_tabs[_cti]:
                        st.plotly_chart(
                            chart_taxa_real(
                                snap.dap if snap else [],
                                delta_ipca_bps=delta_ipca_bps,
                                legs=valid),
                            use_container_width=True)
        st.plotly_chart(
            chart_pnl_barras(valid, scenario_key, magnitude,
                             delta_fx_pct=delta_fx_pct,
                             delta_ipca_bps=delta_ipca_bps,
                             delta_cupom_bps=delta_cupom_bps),
            use_container_width=True)

        du_min = min(l["du"] for l in rate_legs) if rate_legs else 0
        du_max = max(l["du"] for l in rate_legs) if rate_legs else 1
        total_pnl = 0.0
        for l in valid:
            delta = (0.0 if l["info"].conv == "price"
                     else calc_scenario_delta(
                         l["du"], du_min, du_max, scenario_key, magnitude))
            total_pnl += calc_leg_pnl(l, delta,
                                       delta_fx_pct=delta_fx_pct,
                                       delta_ipca_bps=delta_ipca_bps,
                                       delta_cupom_bps=delta_cupom_bps)
        st.metric("P&L Total do Cenario", f"R$ {total_pnl:+,.0f}")

        st.divider()
        st.markdown(render_mtm_html(valid, scenario_key,
                                     delta_fx_pct=delta_fx_pct,
                                     delta_ipca_bps=delta_ipca_bps,
                                     delta_cupom_bps=delta_cupom_bps),
                    unsafe_allow_html=True)

        st.divider()
        pc1, pc2 = st.columns(2)
        with pc1:
            st.plotly_chart(
                chart_pnl_consolidado(valid,
                                      delta_fx_pct=delta_fx_pct,
                                      delta_ipca_bps=delta_ipca_bps,
                                      delta_cupom_bps=delta_cupom_bps),
                use_container_width=True)
        with pc2:
            st.plotly_chart(
                chart_pnl_por_perna(valid,
                                    delta_fx_pct=delta_fx_pct,
                                    delta_ipca_bps=delta_ipca_bps,
                                    delta_cupom_bps=delta_cupom_bps),
                use_container_width=True)

with tab_mkt:
    if snap and snap.timestamp:
        st.caption(f"Atualizado: {snap.timestamp}")

        st.subheader("Indicadores BCB")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("CDI Over", f"{snap.cdi_aa:.2f}% a.a.")
        mc2.metric("CDI Dia", f"{snap.cdi_over_dia:.6f}%")
        mc3.metric("PTAX Venda", f"R$ {snap.ptax:.4f}")
        mc4.metric("Spot USD", f"R$ {snap.spot_usd:.4f}" if snap.spot_usd > 0 else "--")

        st.divider()

        st.subheader("Curva DI Futuro (B3)")
        if snap.di1:
            import pandas as pd
            di_df = pd.DataFrame([
                {"Ticker": c["symb"], "Vcto": c["vcto"], "Last": c["last"],
                 "Bid": c["bid"], "Ask": c["ask"], "Ajuste": c["ajuste"],
                 "OI": f"{c['oi']:,}", "Volume": f"{c['volume']:,}"}
                for c in snap.di1 if c["last"] > 0 or c["ajuste"] > 0
            ])
            st.dataframe(di_df, use_container_width=True, hide_index=True, height=400)

        col_dap, col_frc = st.columns(2)
        with col_dap:
            st.subheader("DAP — Cupom IPCA (B3)")
            if snap.dap:
                dap_df = pd.DataFrame([
                    {"Ticker": c["symb"], "Vcto": c["vcto"],
                     "Last": c["last"] if c["last"] > 0 else "--",
                     "Ajuste": c["ajuste"]}
                    for c in snap.dap
                ])
                st.dataframe(dap_df, use_container_width=True, hide_index=True)

        with col_frc:
            st.subheader("FRC — Cupom Cambial (B3)")
            if snap.frc:
                frc_df = pd.DataFrame([
                    {"Ticker": c["symb"], "Vcto": c["vcto"],
                     "Last": c["last"] if c["last"] > 0 else "--",
                     "Ajuste": c["ajuste"]}
                    for c in snap.frc if c["ajuste"] > 0
                ])
                st.dataframe(frc_df, use_container_width=True, hide_index=True)

        col_dol, col_ddi = st.columns(2)
        with col_dol:
            st.subheader("DOL — Dolar Futuro (B3)")
            if snap.dol:
                dol_df = pd.DataFrame([
                    {"Ticker": c["symb"], "Vcto": c["vcto"],
                     "Last": c["last"], "Bid": c["bid"], "Ask": c["ask"],
                     "Ajuste": c["ajuste"]}
                    for c in snap.dol
                ])
                st.dataframe(dol_df, use_container_width=True, hide_index=True)

        with col_ddi:
            st.subheader("DDI — Cupom Cambial Sujo (B3)")
            if snap.ddi:
                ddi_df = pd.DataFrame([
                    {"Ticker": c["symb"], "Vcto": c["vcto"],
                     "Last": c["last"] if c["last"] > 0 else "—",
                     "Ajuste": c["ajuste"]}
                    for c in snap.ddi if c["ajuste"] > 0 or c["last"] > 0
                ])
                st.dataframe(ddi_df, use_container_width=True, hide_index=True)
            else:
                st.caption("Sem dados DDI disponíveis.")

        st.divider()
        st.subheader("Vencimentos TPF")
        from lib.market_data import get_tpf_vctos
        tpf_types = ["LTN", "NTN-F", "NTN-B", "LFT"]
        tpf_rows = []
        for tp in tpf_types:
            for v in get_tpf_vctos(tp):
                tpf_rows.append({"Tipo": tp, "Vencimento": v})
        if tpf_rows:
            st.dataframe(pd.DataFrame(tpf_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Clique em 'Atualizar Dados de Mercado' para carregar os dados.")

with tab_form:
    render_formulas()
