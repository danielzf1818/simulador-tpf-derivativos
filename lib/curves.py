"""Interpolacao de curvas de juros — flat forward e cubic spline.

Referencia: Manual de Curvas B3 V14 (Nov/2024).
Convencoes:
- DI/Pre/DAP: exponencial, base 252 DU
- Cupom cambial (DDI/FRC/DOC): linear, base 360 DC
"""

from __future__ import annotations
from typing import Optional


def flat_forward_interp(vertices: list[tuple[int, float]], du_alvo: int) -> Optional[float]:
    """Interpola taxa spot via flat forward entre vertices da curva.

    Args:
        vertices: lista de (du, taxa_aa) ordenada por du. Taxa em % a.a.
        du_alvo: DU para o qual se deseja a taxa interpolada.

    Returns:
        Taxa interpolada em % a.a., ou None se fora do range.

    Formula (B3 V14, exp252):
        fwd = [(1+r2)^(du2/252) / (1+r1)^(du1/252)]^(252/(du2-du1)) - 1
        (1+r_alvo)^(du_alvo/252) = (1+r1)^(du1/252) * (1+fwd)^((du_alvo-du1)/252)
        r_alvo = [(1+r1)^(du1/252) * (1+fwd)^((du_alvo-du1)/252)]^(252/du_alvo) - 1
    """
    if not vertices or du_alvo <= 0:
        return None

    verts = sorted(vertices, key=lambda x: x[0])

    if du_alvo <= verts[0][0]:
        return verts[0][1]
    if du_alvo >= verts[-1][0]:
        return verts[-1][1]

    du1, r1 = None, None
    du2, r2 = None, None
    for j in range(len(verts) - 1):
        if verts[j][0] <= du_alvo <= verts[j + 1][0]:
            du1, r1 = verts[j]
            du2, r2 = verts[j + 1]
            break

    if du1 is None:
        return None

    if du1 == du2:
        return r1

    if du_alvo == du1:
        return r1
    if du_alvo == du2:
        return r2

    r1d = r1 / 100
    r2d = r2 / 100

    f1 = (1 + r1d) ** (du1 / 252)
    f2 = (1 + r2d) ** (du2 / 252)

    fwd = (f2 / f1) ** (252 / (du2 - du1)) - 1

    f_alvo = f1 * (1 + fwd) ** ((du_alvo - du1) / 252)
    r_alvo = f_alvo ** (252 / du_alvo) - 1

    return r_alvo * 100


def flat_forward_curve(vertices: list[tuple[int, float]],
                       du_step: int = 1) -> list[tuple[int, float]]:
    """Gera curva suave via flat forward a cada du_step DUs.

    Args:
        vertices: lista de (du, taxa_aa) ordenada por du. Taxa em % a.a.
        du_step: passo em DUs entre pontos da curva.

    Returns:
        Lista de (du, taxa_aa) com pontos interpolados.
    """
    if not vertices:
        return []

    verts = sorted(vertices, key=lambda x: x[0])
    du_min = verts[0][0]
    du_max = verts[-1][0]

    result = []
    du = du_min
    while du <= du_max:
        r = flat_forward_interp(verts, du)
        if r is not None:
            result.append((du, r))
        du += du_step

    if result and result[-1][0] != du_max:
        result.append((du_max, verts[-1][1]))

    return result


def flat_forward_lin360(vertices: list[tuple[int, float]], dc_alvo: int) -> Optional[float]:
    """Interpola taxa via flat forward na convencao linear 360 DC.

    Usado para cupom cambial (DDI, FRC, DOC).

    Args:
        vertices: lista de (dc, taxa_aa) ordenada por dc. Taxa em % a.a. lin360.
        dc_alvo: DC alvo.

    Formula:
        (1+cc_L*dc_L/360) = (1+cc_C*dc_C/360) * (1+fwd*(dc_L-dc_C)/360)
        fwd = [(1+cc_L*dc_L/360)/(1+cc_C*dc_C/360) - 1] * 360/(dc_L-dc_C)
    """
    if not vertices or dc_alvo <= 0:
        return None

    verts = sorted(vertices, key=lambda x: x[0])

    if dc_alvo <= verts[0][0]:
        return verts[0][1]
    if dc_alvo >= verts[-1][0]:
        return verts[-1][1]

    dc1, r1 = None, None
    dc2, r2 = None, None
    for j in range(len(verts) - 1):
        if verts[j][0] <= dc_alvo <= verts[j + 1][0]:
            dc1, r1 = verts[j]
            dc2, r2 = verts[j + 1]
            break

    if dc1 is None:
        return None

    if dc_alvo == dc1:
        return r1
    if dc_alvo == dc2:
        return r2

    r1d = r1 / 100
    r2d = r2 / 100

    f1 = 1 + r1d * dc1 / 360
    f2 = 1 + r2d * dc2 / 360

    fwd = (f2 / f1 - 1) * 360 / (dc2 - dc1)
    f_alvo = f1 * (1 + fwd * (dc_alvo - dc1) / 360)
    r_alvo = (f_alvo - 1) * 360 / dc_alvo

    return r_alvo * 100


def build_di_vertices(di1_contracts: list[dict], liq_date) -> list[tuple[int, float]]:
    """Converte contratos DI1 da B3 em vertices (du, taxa_aa).

    Args:
        di1_contracts: lista de dicts com symb, vcto, last, ajuste.
        liq_date: data de liquidacao (date object).

    Returns:
        Lista de (du, taxa_aa) ordenada por du.
    """
    from .calendar import du_entre
    from datetime import date

    pairs = []
    for c in di1_contracts:
        rate = c.get("last", 0)
        if rate <= 0:
            rate = c.get("ajuste", 0)
        if rate <= 0:
            continue
        vp = c["vcto"].split("-")
        vd = date(int(vp[0]), int(vp[1]), int(vp[2]))
        du = du_entre(liq_date, vd)
        if du > 0:
            pairs.append((du, rate))

    pairs.sort()
    return pairs


def build_dap_vertices(dap_contracts: list[dict], liq_date) -> list[tuple[int, float]]:
    """Converte contratos DAP da B3 em vertices (du, taxa_aa)."""
    from .calendar import du_entre
    from datetime import date

    pairs = []
    for c in dap_contracts:
        rate = c.get("last", 0)
        if rate <= 0:
            rate = c.get("ajuste", 0)
        if rate <= 0:
            continue
        vp = c["vcto"].split("-")
        vd = date(int(vp[0]), int(vp[1]), int(vp[2]))
        du = du_entre(liq_date, vd)
        if du > 0:
            pairs.append((du, rate))

    pairs.sort()
    return pairs


def build_frc_vertices(frc_contracts: list[dict], liq_date) -> list[tuple[int, float]]:
    """Converte contratos FRC da B3 em vertices (dc, taxa_aa).

    FRC usa convencao linear 360 DC.
    """
    from .calendar import dc_entre
    from datetime import date

    pairs = []
    for c in frc_contracts:
        rate = c.get("last", 0)
        if rate <= 0:
            rate = c.get("ajuste", 0)
        if rate <= 0:
            continue
        vp = c["vcto"].split("-")
        vd = date(int(vp[0]), int(vp[1]), int(vp[2]))
        dc = dc_entre(liq_date, vd)
        if dc > 0:
            pairs.append((dc, rate))

    pairs.sort()
    return pairs


def flat_forward_curve_lin360(vertices: list[tuple[int, float]],
                              dc_step: int = 5) -> list[tuple[int, float]]:
    """Gera curva suave de cupom cambial via flat forward lin360."""
    if not vertices:
        return []
    verts = sorted(vertices, key=lambda x: x[0])
    dc_min = verts[0][0]
    dc_max = verts[-1][0]
    result = []
    dc = dc_min
    while dc <= dc_max:
        r = flat_forward_lin360(verts, dc)
        if r is not None:
            result.append((dc, r))
        dc += dc_step
    if result and result[-1][0] != dc_max:
        result.append((dc_max, verts[-1][1]))
    return result


def build_forward_curve(di_vertices: list[tuple[int, float]],
                        frc_vertices: list[tuple[int, float]],
                        spot: float,
                        liq_date,
                        dc_step: int = 10) -> list[tuple[int, float, float]]:
    """Calcula curva de dolar forward implicito pela paridade coberta.

    Para cada vertice da curva DI, calcula:
        Fwd(t) = Spot * (1+pre)^(DU/252) / (1+cupom*DC/360)

    Interpola cupom cambial via flat_forward_lin360 para cada DC.

    Args:
        di_vertices: (du, taxa_pre) da curva DI
        frc_vertices: (dc, taxa_cupom) da curva FRC
        spot: dolar spot R$/USD
        liq_date: data de liquidacao
        dc_step: passo em DC

    Returns:
        Lista de (du, dc, fwd) ordenada por du.
    """
    from .calendar import dc_entre, du_entre
    from datetime import date, timedelta

    if not di_vertices or not frc_vertices or spot <= 0:
        return []

    result = []
    for du, pre in di_vertices:
        approx_dc = round(du * 365 / 252)
        cupom = flat_forward_lin360(frc_vertices, approx_dc)
        if cupom is None:
            continue
        fator_pre = (1 + pre / 100) ** (du / 252)
        fator_cupom = 1 + (cupom / 100) * approx_dc / 360
        if fator_cupom > 0:
            fwd = spot * fator_pre / fator_cupom
            result.append((du, approx_dc, fwd))

    return result
