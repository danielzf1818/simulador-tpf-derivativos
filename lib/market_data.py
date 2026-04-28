"""Fetcher de dados de mercado ao vivo — B3, BCB e ANBIMA.

Fontes:
- B3: DI1, DAP, FRC, DDI, DOL (gratuita, sem token)
- BCB: CDI Over, PTAX, Selic, IPCA (gratuita, sem token)
- ANBIMA: TPF taxas indicativas, VNA, curvas ETTJ (requer token)

Cache em memoria com TTL configuravel.
"""

from __future__ import annotations
import json
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime


CACHE_TTL_SECONDS = 300  # 5 minutos


@dataclass
class CacheEntry:
    data: object
    timestamp: float


_cache: dict[str, CacheEntry] = {}


def _fetch_json(url: str, headers: dict = None, timeout: int = 10):
    """Fetch JSON from URL with optional headers."""
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def _cached_fetch(key: str, url: str, headers: dict = None, ttl: int = CACHE_TTL_SECONDS):
    """Fetch with in-memory cache."""
    now = time.time()
    if key in _cache and (now - _cache[key].timestamp) < ttl:
        return _cache[key].data
    data = _fetch_json(url, headers)
    if "error" not in data:
        _cache[key] = CacheEntry(data, now)
    return data


def clear_cache():
    """Limpa todo o cache."""
    _cache.clear()


# ============================================================
# B3 — Derivativos
# ============================================================

B3_BASE = "https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation"


def _parse_b3_contracts(asset_code: str) -> list[dict]:
    """Busca todos os contratos de um derivativo na B3.

    Retorna lista de dicts com: symb, vcto, last, bid, ask, ajuste, oi, volume.
    """
    data = _cached_fetch(f"b3_{asset_code}", f"{B3_BASE}/{asset_code}")
    if "error" in data or "Scty" not in data:
        return []

    contracts = []
    for c in data["Scty"]:
        symb = c.get("symb", "")
        if not symb or len(symb) > 8:
            continue

        contracts.append({
            "symb": symb,
            "vcto": c.get("asset", {}).get("AsstSummry", {}).get("mtrtyCode", ""),
            "last": c.get("SctyQtn", {}).get("curPrc", 0),
            "bid": c.get("buyOffer", {}).get("price", 0),
            "ask": c.get("sellOffer", {}).get("price", 0),
            "ajuste": c.get("SctyQtn", {}).get("prvsDayAdjstmntPric", 0),
            "oi": c.get("asset", {}).get("AsstSummry", {}).get("opnCtrcts", 0),
            "volume": c.get("asset", {}).get("AsstSummry", {}).get("traddCtrctsQty", 0),
        })

    return sorted(contracts, key=lambda x: x["vcto"])


def fetch_di1() -> list[dict]:
    """Busca todos os contratos DI1 da B3.

    Retorna: [{symb, vcto, last, bid, ask, ajuste, oi, volume}, ...]
    Taxa em % a.a. exp252.
    """
    return _parse_b3_contracts("DI1")


def fetch_dap() -> list[dict]:
    """Busca todos os contratos DAP da B3. Taxa real % a.a. exp252."""
    return _parse_b3_contracts("DAP")


def fetch_frc() -> list[dict]:
    """Busca todos os contratos FRC da B3. Cupom limpo % a.a. lin360."""
    return _parse_b3_contracts("FRC")


def fetch_ddi() -> list[dict]:
    """Busca todos os contratos DDI da B3. Cupom sujo % a.a. lin360."""
    return _parse_b3_contracts("DDI")


def fetch_dol() -> list[dict]:
    """Busca contratos DOL (futuros puros, sem opcoes) da B3.

    Cotacao em R$ por USD 1.000.
    """
    data = _cached_fetch("b3_DOL", f"{B3_BASE}/DOL")
    if "error" in data or "Scty" not in data:
        return []

    contracts = []
    for c in data["Scty"]:
        symb = c.get("symb", "")
        if len(symb) != 6 or not symb.startswith("DOL"):
            continue
        last = c.get("SctyQtn", {}).get("curPrc", 0)
        if last == 0:
            continue
        contracts.append({
            "symb": symb,
            "vcto": c.get("asset", {}).get("AsstSummry", {}).get("mtrtyCode", ""),
            "last": last,
            "bid": c.get("buyOffer", {}).get("price", 0),
            "ask": c.get("sellOffer", {}).get("price", 0),
            "ajuste": c.get("SctyQtn", {}).get("prvsDayAdjstmntPric", 0),
            "oi": c.get("asset", {}).get("AsstSummry", {}).get("opnCtrcts", 0),
        })

    return sorted(contracts, key=lambda x: x["vcto"])


# ============================================================
# BCB — Indicadores
# ============================================================

BCB_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs"


def fetch_cdi_over(ultimos: int = 5) -> list[dict]:
    """CDI Over diario (serie 12). Retorna [{data, valor}, ...].

    Valor em % ao dia. Para converter: taxa_aa = (1 + valor/100)^252 - 1.
    """
    return _cached_fetch("bcb_cdi", f"{BCB_BASE}.12/dados/ultimos/{ultimos}?formato=json")


def fetch_ptax(ultimos: int = 5) -> list[dict]:
    """PTAX venda (serie 1). Retorna [{data, valor}, ...]. Valor em R$/USD."""
    return _cached_fetch("bcb_ptax", f"{BCB_BASE}.1/dados/ultimos/{ultimos}?formato=json")


def fetch_selic_meta(ultimos: int = 5) -> list[dict]:
    """Selic Meta (serie 432). Retorna [{data, valor}, ...]."""
    return _cached_fetch("bcb_selic", f"{BCB_BASE}.432/dados/ultimos/{ultimos}?formato=json")


def fetch_ipca(ultimos: int = 12) -> list[dict]:
    """IPCA mensal (serie 433). Retorna [{data, valor}, ...]."""
    return _cached_fetch("bcb_ipca", f"{BCB_BASE}.433/dados/ultimos/{ultimos}?formato=json")


def cdi_over_to_annual(cdi_dia: float) -> float:
    """Converte CDI over diario (% ao dia) para taxa anual (% a.a.).

    Formula: taxa_aa = ((1 + cdi_dia/100)^252 - 1) * 100
    """
    return ((1 + cdi_dia / 100) ** 252 - 1) * 100


# ============================================================
# ANBIMA — TPF e Curvas (requer token)
# ============================================================

ANBIMA_PROD = "https://api.anbima.com.br"
ANBIMA_SANDBOX = "https://api-sandbox.anbima.com.br"


def anbima_get_token(client_id: str, client_secret: str) -> str:
    """Gera access_token ANBIMA via client_credentials.

    Token expira em 3600s (1h). Cached internamente.
    """
    cached = _cache.get("anbima_token")
    if cached and (time.time() - cached.timestamp) < 3500:
        return cached.data

    import base64
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        f"{ANBIMA_PROD}/oauth/access-token",
        data=json.dumps({"grant_type": "client_credentials"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Basic {credentials}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read().decode())["access_token"]
            _cache["anbima_token"] = CacheEntry(token, time.time())
            return token
    except Exception:
        return ""


def _anbima_fetch(path: str, client_id: str, token: str, sandbox: bool = True):
    """Fetch ANBIMA API."""
    base = ANBIMA_SANDBOX if sandbox else ANBIMA_PROD
    headers = {"access_token": token, "client_id": client_id}
    return _cached_fetch(f"anbima_{path}", f"{base}{path}", headers)


def fetch_tpf_anbima(client_id: str, token: str, sandbox: bool = True) -> list[dict]:
    """Taxas indicativas de TPF (mercado secundario).

    Retorna: [{tipo_titulo, data_vencimento, taxa_indicativa, pu, codigo_isin}, ...]
    """
    data = _anbima_fetch("/feed/precos-indices/v1/titulos-publicos/mercado-secundario-TPF", client_id, token, sandbox)
    if isinstance(data, dict) and "error" in data:
        return []
    return data if isinstance(data, list) else []


def fetch_vna_anbima(client_id: str, token: str, sandbox: bool = True) -> list[dict]:
    """VNA de titulos indexados (LFT, NTN-B, NTN-C)."""
    data = _anbima_fetch("/feed/precos-indices/v1/titulos-publicos/vna", client_id, token, sandbox)
    if isinstance(data, dict) and "error" in data:
        return []
    return data if isinstance(data, list) else []


def fetch_curvas_anbima(client_id: str, token: str, sandbox: bool = True) -> list[dict]:
    """Curvas de juros ETTJ (pre, IPCA, implicita) com vertices em DU."""
    data = _anbima_fetch("/feed/precos-indices/v1/titulos-publicos/curvas-juros", client_id, token, sandbox)
    if isinstance(data, dict) and "error" in data:
        return []
    return data if isinstance(data, list) else []


# ============================================================
# Agregador — dados consolidados
# ============================================================

@dataclass
class MarketSnapshot:
    """Snapshot consolidado de dados de mercado."""
    timestamp: str = ""
    cdi_over_dia: float = 0
    cdi_aa: float = 0
    ptax: float = 0
    spot_usd: float = 0
    di1: list = field(default_factory=list)
    dap: list = field(default_factory=list)
    frc: list = field(default_factory=list)
    ddi: list = field(default_factory=list)
    dol: list = field(default_factory=list)
    tpf: list = field(default_factory=list)


def fetch_all(anbima_client_id: str = "", anbima_secret: str = "", sandbox: bool = True) -> MarketSnapshot:
    """Busca todos os dados de mercado de uma vez.

    B3 e BCB sao sempre buscados. ANBIMA so se client_id+secret forem fornecidos.
    """
    snap = MarketSnapshot()
    snap.timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # BCB
    cdi_data = fetch_cdi_over(1)
    if cdi_data and not isinstance(cdi_data, dict):
        snap.cdi_over_dia = float(cdi_data[-1].get("valor", 0))
        snap.cdi_aa = cdi_over_to_annual(snap.cdi_over_dia)

    ptax_data = fetch_ptax(1)
    if ptax_data and not isinstance(ptax_data, dict):
        snap.ptax = float(ptax_data[-1].get("valor", 0))

    # B3
    snap.di1 = fetch_di1()
    snap.dap = fetch_dap()
    snap.frc = fetch_frc()
    snap.ddi = fetch_ddi()
    snap.dol = fetch_dol()

    # DOL spot from first future minus casado (approximate)
    if snap.dol:
        snap.spot_usd = snap.dol[0]["last"] / 1000 - 0.005

    # ANBIMA
    if anbima_client_id and anbima_secret:
        token = anbima_get_token(anbima_client_id, anbima_secret)
        if token:
            snap.tpf = fetch_tpf_anbima(anbima_client_id, token, sandbox)

    return snap


# ============================================================
# Vencimentos de TPF ativos (padronizados pelo Tesouro Nacional)
# ============================================================

TPF_VENCIMENTOS = {
    "LTN": [
        "2026-07-01", "2026-10-01", "2027-01-01", "2027-04-01",
        "2027-07-01", "2027-10-01", "2028-01-01", "2028-04-01",
        "2028-07-01", "2028-10-01", "2029-01-01",
    ],
    "NTN-F": [
        "2027-01-01", "2029-01-01", "2031-01-01", "2033-01-01", "2035-01-01",
    ],
    "NTN-B": [
        "2026-08-15", "2027-05-15", "2028-08-15", "2029-05-15",
        "2030-08-15", "2032-08-15", "2035-05-15", "2040-08-15",
        "2045-05-15", "2050-08-15", "2055-05-15", "2060-08-15",
    ],
    "LFT": [
        "2026-09-01", "2027-03-01", "2027-09-01", "2028-03-01",
        "2028-09-01", "2029-03-01", "2029-09-01",
    ],
}


def get_tpf_vctos(tipo: str) -> list[str]:
    """Retorna lista de vencimentos disponiveis para um tipo de TPF.

    Formato: YYYY-MM-DD.
    """
    return TPF_VENCIMENTOS.get(tipo, [])


def find_di1_rate_for_date(di1_contracts: list[dict], target_date: str) -> float:
    """Encontra a taxa DI1 mais proxima de uma data alvo.

    Usado para interpolar a taxa de mercado para um TPF cujo vencimento
    pode nao coincidir exatamente com um DI1.
    """
    if not di1_contracts:
        return 0

    best = None
    best_diff = float("inf")
    for c in di1_contracts:
        diff = abs(_date_diff_days(c["vcto"], target_date))
        if diff < best_diff:
            best_diff = diff
            best = c
    return best["last"] if best and best["last"] > 0 else (best["ajuste"] if best else 0)


def _date_diff_days(d1_str: str, d2_str: str) -> int:
    """Diferenca em dias entre duas datas em formato YYYY-MM-DD."""
    from datetime import date
    p1 = d1_str.split("-")
    p2 = d2_str.split("-")
    a = date(int(p1[0]), int(p1[1]), int(p1[2]))
    b = date(int(p2[0]), int(p2[1]), int(p2[2]))
    return (a - b).days
