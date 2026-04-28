"""Exposicao economica, deteccao de estrategia, fatores de risco e sugestao de hedge."""

from __future__ import annotations
from .instruments import INSTRUMENTS, duration, dv01


def get_exposure(instrumento: str, direcao: str, taxa: float) -> dict:
    """Retorna ativo/passivo economico de uma perna.

    Compra LTN    → Ativo: Pre X%,     Passivo: —
    Compra DI1    → Ativo: CDI,        Passivo: Pre Y%
    Compra DOL    → Ativo: DOL cotacao, Passivo: —
    Compra DDI    → Ativo: CDI,        Passivo: CupSujo X%
    Compra FRC    → Ativo: CDI,        Passivo: CupLimpo X%
    Compra DAP    → Ativo: IPCA,       Passivo: IPCA+ Y%
    """
    info = INSTRUMENTS[instrumento]
    rs = f"{taxa:.3f}%"

    if info.conv == "price":
        cotacao = f"DOL {taxa:.1f}"
        return {"ativo": cotacao, "passivo": "—"} if direcao == "C" else {"ativo": "—", "passivo": cotacao}

    if info.type == "tpf":
        val = f"{info.benchmark} {rs}"
        return {"ativo": val, "passivo": "—"} if direcao == "C" else {"ativo": "—", "passivo": val}

    if info.type == "cupom":
        val = f"{info.benchmark} {rs}"
        return {"ativo": "CDI", "passivo": val} if direcao == "C" else {"ativo": val, "passivo": "CDI"}

    pay_bm = "IPCA+" if instrumento == "DAP" else "Pre"
    rec_bm = "CDI" if instrumento == "DI1" else "IPCA"
    val = f"{pay_bm} {rs}"
    return {"ativo": rec_bm, "passivo": val} if direcao == "C" else {"ativo": val, "passivo": rec_bm}


def detect_strategy(legs: list[dict], spot: float = 4.9724) -> dict:
    """Detecta estrategia conhecida a partir das pernas.

    Combinacoes reconhecidas:
    - LTN/NTN-F + DI1 (mesmo vcto, mesma direcao) → Casada Pre (CDI + spread bps)
    - NTN-B + DAP (mesmo vcto, mesma direcao)      → Casada IPCA (IPCA + spread bps)
    - DOL + DI1 (mesmo vcto, mesma direcao)         → Cupom Cambial Sintetico
    - DOL + DI1 (mesma vcto, direcao oposta)        → Direcional FX puro
    - Perna unica                                    → Direcional
    """
    from .instruments import cupom_cambial_implicito

    if len(legs) == 1:
        r = legs[0]
        info = INSTRUMENTS[r["instrument"]]
        d = "Comprado" if r["direction"] == "C" else "Vendido"
        if info.conv == "price":
            return {"result": f"{d} DOL {r['parsed']['label']} a {r['taxa']:.1f}", "type": "single"}
        if info.conv == "lin360":
            return {"result": f"{d} {info.benchmark} {r['taxa']:.2f}% a.a. lin360 ({r['parsed']['label']}), PU {r['pu']:.2f}", "type": "single"}
        return {"result": f"{d} {r['instrument']} {r['parsed']['label']} a {r['taxa']:.3f}%, PU {r['pu']:.2f}, Fin R$ {r['fin']:,.0f}", "type": "single"}

    same_vcto = len(legs) > 1 and all(l["parsed"]["label"] == legs[0]["parsed"]["label"] for l in legs)
    tpf = next((l for l in legs if INSTRUMENTS[l["instrument"]].type == "tpf"), None)
    di = next((l for l in legs if l["instrument"] == "DI1"), None)
    dap = next((l for l in legs if l["instrument"] == "DAP"), None)
    dol = next((l for l in legs if l["instrument"] == "DOL"), None)

    if tpf and di and same_vcto and tpf["direction"] == di["direction"]:
        spread = (tpf["tax_fin"] - di["taxa"]) * 100
        bmk = "IPCA" if tpf["instrument"] == "NTN-B" else "CDI"
        return {"result": f"{bmk} + {spread:+.2f} bps ({tpf['instrument']} {tpf['tax_fin']:.3f}% vs DI1 {di['taxa']:.3f}%)",
                "type": "casada", "spread": spread, "bmk": bmk, "tpf": tpf, "di": di}

    if tpf and dap and same_vcto and tpf["direction"] == dap["direction"] and tpf["instrument"] == "NTN-B":
        spread = (tpf["tax_fin"] - dap["taxa"]) * 100
        return {"result": f"IPCA + {spread:+.2f} bps (NTN-B {tpf['tax_fin']:.3f}% vs DAP {dap['taxa']:.3f}%)",
                "type": "casada", "spread": spread, "bmk": "IPCA", "tpf": tpf, "di": dap}

    if dol and di and same_vcto and dol["direction"] == di["direction"]:
        cupom = cupom_cambial_implicito(spot, dol["taxa"], di["taxa"], di["du"], dol["dc"])
        direc = "Comprado" if dol["direction"] == "C" else "Vendido"
        return {"result": f"{direc} Cupom Cambial Sintetico: {cupom:.2f}% a.a. lin360",
                "type": "cupom_sint", "cupom": cupom, "dol": dol, "di": di}

    if dol and di and same_vcto and dol["direction"] != di["direction"]:
        direc = "Long" if dol["direction"] == "C" else "Short"
        return {"result": f"{direc} USD/BRL puro (DOL {dol['taxa']:.1f}, DI1 {di['taxa']:.3f}%)", "type": "fx_direcional"}

    return {"result": "Combinacao customizada", "type": "custom"}


def analyze_risk_factors(legs: list[dict], strategy: dict) -> list[dict]:
    """Analisa quais fatores de risco a operacao esta exposta.

    Fatores avaliados:
    - Nivel (shift paralelo)
    - Inclinacao (steepening/flattening)
    - Curvatura (butterfly)
    - Convexidade (gamma)
    - Spread (basis entre titulo e DI)
    - Cambio (USD/BRL)
    - Cupom cambial
    - Inflacao (IPCA)
    """
    factors = []
    insts = {l["instrument"] for l in legs}
    has_tpf = any(INSTRUMENTS[l["instrument"]].type == "tpf" for l in legs)
    has_cupom_tpf = any(INSTRUMENTS[l["instrument"]].cup_sem > 0 for l in legs)
    has_di = "DI1" in insts
    has_dap = "DAP" in insts
    has_dol = "DOL" in insts
    has_ntnb = "NTN-B" in insts
    same_vcto = len(legs) > 1 and all(l["parsed"]["label"] == legs[0]["parsed"]["label"] for l in legs)
    is_casada = strategy["type"] == "casada"

    if len(legs) == 1:
        info = INSTRUMENTS[legs[0]["instrument"]]
        if info.conv == "price":
            factors.append({"fator": "Cambio (USD/BRL)", "exposto": True, "desc": f"Direcional em dolar — DV01 R$ {legs[0]['dv01_total']:.0f}/ponto"})
        else:
            factors.append({"fator": "Nivel (shift paralelo)", "exposto": True, "desc": f"DV01 total: R$ {legs[0]['dv01_total']:.0f} por bp"})
            if has_cupom_tpf:
                factors.append({"fator": "Inclinacao", "exposto": True, "desc": "Titulo com cupom tem fluxos em multiplos vertices"})
            if has_ntnb:
                factors.append({"fator": "Inflacao (IPCA)", "exposto": True, "desc": "NTN-B indexada ao IPCA"})
        return factors

    if is_casada and same_vcto and not has_cupom_tpf:
        factors.append({"fator": "Nivel (shift paralelo)", "exposto": False, "desc": "Hedge por mesmo vencimento — cancela em 1a ordem"})
    elif is_casada and has_cupom_tpf:
        factors.append({"fator": "Nivel (shift paralelo)", "exposto": False, "desc": "Hedge por DV01 — cancela shift paralelo em 1a ordem"})
    elif has_dol and has_di:
        factors.append({"fator": "Nivel (taxa pre BRL)", "exposto": False, "desc": "DOL+DI1 cancela exposicao a taxa pre"})
    else:
        factors.append({"fator": "Nivel (shift paralelo)", "exposto": True, "desc": "Pernas com vencimentos ou benchmarks diferentes"})

    if has_dol and has_di:
        factors.append({"fator": "Cupom Cambial", "exposto": True, "desc": "Posicao sintetica de cupom cambial. Se o cupom implicito mudar, P&L nao-zero."})

    if is_casada and has_cupom_tpf:
        tpf_name = next(l["instrument"] for l in legs if INSTRUMENTS[l["instrument"]].cup_sem > 0)
        factors.append({"fator": "Inclinacao (steepening)", "exposto": True,
                        "desc": f"{tpf_name} tem cupons em vertices intermediarios; DI1 cobre apenas 1 vertice."})
        factors.append({"fator": "Curvatura (butterfly)", "exposto": True,
                        "desc": "Convexidade diferente: titulo com cupom vs DI1 zero-coupon."})
    elif is_casada and not has_cupom_tpf and same_vcto:
        factors.append({"fator": "Inclinacao", "exposto": False, "desc": "Mesmo vertice, sem fluxos intermediarios"})
        factors.append({"fator": "Curvatura", "exposto": False, "desc": "Ambos zero-coupon, convexidade similar"})

    if has_cupom_tpf and (has_di or has_dap):
        tpf_leg = next(l for l in legs if INSTRUMENTS[l["instrument"]].cup_sem > 0)
        deriv_leg = next(l for l in legs if l["instrument"] in ("DI1", "DAP"))
        diff = abs(tpf_leg["d_mac"] - deriv_leg["d_mac"])
        factors.append({"fator": "Convexidade (gamma)", "exposto": diff > 0.3,
                        "desc": f"D.Mac: {tpf_leg['instrument']}={tpf_leg['d_mac']:.2f}a vs {deriv_leg['instrument']}={deriv_leg['d_mac']:.2f}a (diff {diff:.2f}a)"})

    if is_casada:
        factors.append({"fator": "Spread (basis)", "exposto": True,
                        "desc": f"Spread titulo vs DI: {strategy.get('spread', 0):.2f} bps. Risco de abertura/fechamento."})

    if has_dol and not has_di:
        factors.append({"fator": "Cambio (USD/BRL)", "exposto": True, "desc": "Exposicao direcional a cambio"})
    elif has_dol and has_di:
        factors.append({"fator": "Cambio (USD/BRL)", "exposto": False, "desc": "DOL+DI1 neutraliza cambio puro (expoe cupom cambial)"})

    if has_ntnb and not has_dap:
        factors.append({"fator": "Inflacao (IPCA)", "exposto": True, "desc": "NTN-B sem hedge de inflacao"})
    elif has_ntnb and has_dap:
        factors.append({"fator": "Inflacao (IPCA)", "exposto": False, "desc": "NTN-B + DAP hedgeia inflacao (expoe spread IPCA)"})

    return factors


def suggest_hedge(legs: list[dict]):
    """Sugere quantidade de DI1 para hedge de TPF com cupom.

    Calcula DV01 ideal na duration e no vencimento final.
    """
    tpf = next((l for l in legs if INSTRUMENTS[l["instrument"]].cup_sem > 0), None)
    if not tpf:
        return None

    di_rate = 13.65
    di_leg = next((l for l in legs if l["instrument"] in ("DI1", "DAP")), None)
    if di_leg:
        di_rate = di_leg["taxa"]

    du_dur = round(tpf["d_mac"] * 252)
    du_mat = tpf["du"]

    dv01_at_dur = dv01("DI1", di_rate, du_dur, du_dur, 1)
    dv01_at_mat = dv01("DI1", di_rate, du_mat, du_mat, 1)

    n_at_dur = round(tpf["dv01_total"] / dv01_at_dur.unit) if dv01_at_dur.unit else 0
    n_at_mat = round(tpf["dv01_total"] / dv01_at_mat.unit) if dv01_at_mat.unit else 0
    current_n = di_leg["quantity"] if di_leg else 0
    resid = tpf["dv01_total"] - (di_leg["dv01_total"] if di_leg else 0)

    return {
        "tpf": tpf,
        "di_rate": di_rate,
        "du_duration": du_dur,
        "du_maturity": du_mat,
        "n_at_duration": n_at_dur,
        "n_at_maturity": n_at_mat,
        "dv01_at_duration": dv01_at_dur.unit,
        "dv01_at_maturity": dv01_at_mat.unit,
        "current_n": current_n,
        "dv01_residual": resid,
    }
