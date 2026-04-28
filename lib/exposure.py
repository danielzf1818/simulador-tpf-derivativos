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


def _dol_sintetico_fwd(spot: float, taxa_di: float, taxa_frc: float,
                       du: int, dc: int) -> float:
    """Calcula o dolar forward implicito de DI1+FRC pela paridade coberta.

    Futuro/Spot = (1+pre)^(DU/252) / (1+cupom*DC/360)
    """
    fator_pre = (1 + taxa_di / 100) ** (du / 252)
    fator_cupom = 1 + (taxa_frc / 100) * dc / 360
    return spot * fator_pre / fator_cupom if fator_cupom else 0


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

    def _find_pair(legs_pool):
        """Tenta encontrar um par reconhecido dentro das pernas."""
        tpfs = [l for l in legs_pool if INSTRUMENTS[l["instrument"]].type == "tpf"]
        dis = [l for l in legs_pool if l["instrument"] == "DI1"]
        daps = [l for l in legs_pool if l["instrument"] == "DAP"]
        dols = [l for l in legs_pool if l["instrument"] == "DOL"]

        for t in tpfs:
            for d in dis:
                if t["parsed"]["label"] == d["parsed"]["label"] and t["direction"] == d["direction"]:
                    spread = (t["tax_fin"] - d["taxa"]) * 100
                    bmk = "IPCA" if t["instrument"] == "NTN-B" else "CDI"
                    return {"type": "casada", "spread": spread, "bmk": bmk, "tpf": t, "di": d,
                            "result": f"{bmk} {spread:+.2f} bps ({t['instrument']} {t['tax_fin']:.3f}% vs DI1 {d['taxa']:.3f}%)"}

        for t in [l for l in tpfs if l["instrument"] == "NTN-B"]:
            for d in daps:
                if t["parsed"]["label"] == d["parsed"]["label"] and t["direction"] == d["direction"]:
                    spread = (t["tax_fin"] - d["taxa"]) * 100
                    return {"type": "casada", "spread": spread, "bmk": "IPCA", "tpf": t, "di": d,
                            "result": f"IPCA {spread:+.2f} bps (NTN-B {t['tax_fin']:.3f}% vs DAP {d['taxa']:.3f}%)"}

        for dol in dols:
            for d in dis:
                if dol["direction"] == d["direction"]:
                    du_ref = d["du"]
                    dc_ref = d["dc"]
                    cupom = cupom_cambial_implicito(spot, dol["taxa"], d["taxa"], du_ref, dc_ref)
                    direc = "Comprado" if dol["direction"] == "C" else "Vendido"
                    vcto_note = "" if dol["parsed"]["label"] == d["parsed"]["label"] else f" (DOL {dol['parsed']['label']}, DI {d['parsed']['label']})"
                    return {"type": "cupom_sint", "cupom": cupom, "dol": dol, "di": d,
                            "result": f"{direc} Cupom Cambial Sintetico: {cupom:.2f}% a.a.{vcto_note}"}

        frcs = [l for l in legs_pool if l["instrument"] == "FRC"]
        ddis = [l for l in legs_pool if l["instrument"] == "DDI"]

        for d in dis:
            for f in frcs:
                if d["parsed"]["label"] == f["parsed"]["label"] and d["direction"] != f["direction"]:
                    direc = "Comprado" if d["direction"] == "C" else "Vendido"
                    fwd = _dol_sintetico_fwd(spot, d["taxa"], f["taxa"], d["du"], f["dc"])
                    return {"type": "dol_sint", "di": d, "frc": f, "fwd": fwd,
                            "result": f"{direc} Dolar Sintetico (DI1+FRC): fwd ~{fwd:.2f}"}

        for d in dis:
            for dd in ddis:
                if d["parsed"]["label"] == dd["parsed"]["label"] and d["direction"] != dd["direction"]:
                    direc = "Comprado" if d["direction"] == "C" else "Vendido"
                    return {"type": "dol_sint_ddi", "di": d, "ddi": dd,
                            "result": f"{direc} Dolar Sintetico (DI1+DDI)"}

        return None

    pair = _find_pair(legs)
    if pair:
        _used = {id(v) for v in [pair.get("tpf"), pair.get("di"), pair.get("dol"),
                                  pair.get("frc"), pair.get("ddi")] if v is not None}
        remaining = [l for l in legs if id(l) not in _used]
        if remaining:
            extras = []
            for r in remaining:
                info = INSTRUMENTS[r["instrument"]]
                d = "C" if r["direction"] == "C" else "V"
                extras.append(f"{d} {r['instrument']} {r['parsed']['label']}")
            pair["result"] += " + " + ", ".join(extras)
        return pair

    descs = []
    for l in legs:
        info = INSTRUMENTS[l["instrument"]]
        d = "C" if l["direction"] == "C" else "V"
        if info.conv == "price":
            descs.append(f"{d} {l['instrument']} {l['parsed']['label']} {l['taxa']:.1f}")
        else:
            descs.append(f"{d} {l['instrument']} {l['parsed']['label']} {l['taxa']:.3f}%")
    return {"result": " | ".join(descs), "type": "multi"}


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
    has_frc = "FRC" in insts
    has_ddi = "DDI" in insts
    has_ntnb = "NTN-B" in insts
    same_vcto = len(legs) > 1 and all(l["parsed"]["label"] == legs[0]["parsed"]["label"] for l in legs)
    is_casada = strategy["type"] == "casada"
    is_dol_sint = strategy["type"] in ("dol_sint", "dol_sint_ddi")

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

    if is_dol_sint:
        factors.append({"fator": "Cambio (USD/BRL)", "exposto": True,
                        "desc": "DI1+FRC/DDI = dolar forward sintetico. Exposto a variacao cambial."})
        factors.append({"fator": "Nivel (taxa pre BRL)", "exposto": False,
                        "desc": "DI1 e FRC/DDI se cancelam no fator pre — exposicao residual eh cambio."})
        factors.append({"fator": "Cupom Cambial", "exposto": False,
                        "desc": "FRC/DDI hedgeia cupom cambial embutido na posicao."})
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
