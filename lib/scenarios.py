"""Cenarios de curva de juros e calculo de P&L por perna.

Cenarios nomeados do mercado:
- Bull/Bear Parallel: shift uniforme em todas as taxas
- Bull/Bear Steepener: curtos e longos movem em proporcoes diferentes
- Bull/Bear Flattener: idem, direcao oposta
- Positive/Negative Butterfly: barriga vs pontas
"""

from __future__ import annotations
from dataclasses import dataclass
from .instruments import INSTRUMENTS, pu


@dataclass
class ScenarioDefinition:
    name: str
    desc: str

    def delta(self, t: float, mag: float) -> float:
        """Calcula delta em bps para um ponto da curva.

        Args:
            t: posicao normalizada na curva, -1 (curto) a +1 (longo)
            mag: magnitude em bps (sempre positiva para a UI)
        """
        raise NotImplementedError


class BullParallel(ScenarioDefinition):
    """Todas as taxas caem uniformemente."""
    def delta(self, t, mag):
        return -abs(mag)

class BearParallel(ScenarioDefinition):
    """Todas as taxas sobem uniformemente."""
    def delta(self, t, mag):
        return abs(mag)

class BullSteepener(ScenarioDefinition):
    """Curtos caem mais que longos. Tipico: corte de Selic."""
    def delta(self, t, mag):
        a = abs(mag)
        return -a + a * ((t + 1) / 2)

class BearSteepener(ScenarioDefinition):
    """Longos sobem mais que curtos. Tipico: premio a termo, fiscal."""
    def delta(self, t, mag):
        a = abs(mag)
        return a * ((t + 1) / 2)

class BullFlattener(ScenarioDefinition):
    """Longos caem mais que curtos. Tipico: recessao, risk-off."""
    def delta(self, t, mag):
        a = abs(mag)
        return -a * ((t + 1) / 2)

class BearFlattener(ScenarioDefinition):
    """Curtos sobem mais que longos. Tipico: ciclo de alta da Selic."""
    def delta(self, t, mag):
        a = abs(mag)
        return a - a * ((t + 1) / 2)

class PositiveButterfly(ScenarioDefinition):
    """Barriga sobe, pontas caem. Pressao no miolo da curva."""
    def delta(self, t, mag):
        a = abs(mag)
        return a * (1 - t * t) - a * 0.5

class NegativeButterfly(ScenarioDefinition):
    """Barriga cai, pontas sobem. Demanda pelo belly."""
    def delta(self, t, mag):
        a = abs(mag)
        return -a * (1 - t * t) + a * 0.5

class CustomScenario(ScenarioDefinition):
    """Cenario customizado com 3 componentes independentes."""
    def __init__(self):
        super().__init__("Custom", "Defina paralelo, inclinacao e curvatura separadamente")
        self.parallel = 0.0
        self.slope = 0.0
        self.curvature = 0.0

    def delta(self, t, mag):
        return self.parallel + self.slope * t + self.curvature * (-(1 - t * t))


SCENARIOS: dict[str, ScenarioDefinition] = {
    "bull_par":   BullParallel("Bull Parallel", "Todas as taxas caem — flight-to-quality, corte surpresa"),
    "bear_par":   BearParallel("Bear Parallel", "Todas as taxas sobem — surpresa inflacionaria, BCB hawkish"),
    "bull_steep": BullSteepener("Bull Steepener", "Curtos caem mais que longos — corte de Selic"),
    "bear_steep": BearSteepener("Bear Steepener", "Longos sobem mais que curtos — premio a termo, fiscal"),
    "bull_flat":  BullFlattener("Bull Flattener", "Longos caem mais que curtos — recessao, risk-off"),
    "bear_flat":  BearFlattener("Bear Flattener", "Curtos sobem mais que longos — ciclo de alta"),
    "pos_fly":    PositiveButterfly("Positive Butterfly", "Barriga sobe, pontas caem"),
    "neg_fly":    NegativeButterfly("Negative Butterfly", "Barriga cai, pontas sobem"),
    "custom":     CustomScenario(),
}


def calc_scenario_delta(du: int, du_min: int, du_max: int,
                         scenario_key: str, magnitude: float) -> float:
    """Calcula o choque em bps para um vertice especifico.

    Args:
        du: DU do vertice
        du_min: menor DU entre todas as pernas
        du_max: maior DU entre todas as pernas
        scenario_key: chave do cenario em SCENARIOS
        magnitude: magnitude em bps
    """
    du_mid = (du_min + du_max) / 2
    du_range = (du_max - du_min) / 2 or 1
    t = max(-1, min(1, (du - du_mid) / du_range))
    sc = SCENARIOS.get(scenario_key)
    return sc.delta(t, magnitude) if sc else 0


def calc_leg_pnl(leg: dict, delta_bps: float,
                 delta_fx_pct: float = 0.0,
                 delta_ipca_bps: float = 0.0,
                 delta_cupom_bps: float = 0.0) -> float:
    """Calcula P&L de uma perna para choques multi-fator.

    Fatores:
    - delta_bps: variacao na taxa pre (bps) — aplica a DI1, LTN, NTN-F
    - delta_fx_pct: variacao % no spot USD/BRL — aplica a DOL
    - delta_ipca_bps: variacao na taxa real (bps) — aplica a NTN-B, DAP
    - delta_cupom_bps: variacao no cupom cambial (bps) — aplica a DDI, FRC

    Args:
        leg: dict com instrument, tax_fin, du, dc, direction, quantity, taxa
        delta_bps: variacao em bps para taxa pre
        delta_fx_pct: variacao % no spot USD/BRL (ex: +5 = dolar sobe 5%)
        delta_ipca_bps: variacao em bps na taxa real (IPCA)
        delta_cupom_bps: variacao em bps no cupom cambial
    """
    info = INSTRUMENTS[leg["instrument"]]
    inst = leg["instrument"]

    if info.conv == "price":
        sign = 1 if leg["direction"] == "C" else -1
        delta_pts = leg["taxa"] * delta_fx_pct / 100
        return sign * delta_pts * info.mult * leg["quantity"]

    effective_delta = delta_bps
    if inst in ("NTN-B", "DAP"):
        effective_delta = delta_ipca_bps if delta_ipca_bps != 0 else delta_bps
    elif inst in ("DDI", "FRC"):
        effective_delta = delta_cupom_bps if delta_cupom_bps != 0 else delta_bps

    new_rate = leg["tax_fin"] + effective_delta / 100
    new_pu = pu(leg["instrument"], new_rate, leg["du"], leg["dc"])
    old_pu = pu(leg["instrument"], leg["tax_fin"], leg["du"], leg["dc"])
    diff = new_pu - old_pu

    if info.type == "tpf":
        sign = 1 if leg["direction"] == "C" else -1
    else:
        sign = -1 if leg["direction"] == "C" else 1

    return sign * diff * leg["quantity"]
