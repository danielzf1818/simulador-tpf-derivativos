"""Calendario ANBIMA e utilitarios de datas para o mercado brasileiro."""

from datetime import date, timedelta
import re

MONTH_CODES = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
               "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}

MONTH_NAMES = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
               "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

FERIADOS_ANBIMA: set[date] = {
    # 2026
    date(2026,1,1), date(2026,2,16), date(2026,2,17), date(2026,4,3),
    date(2026,4,21), date(2026,5,1), date(2026,6,4), date(2026,9,7),
    date(2026,10,12), date(2026,11,2), date(2026,11,15), date(2026,11,20), date(2026,12,25),
    # 2027
    date(2027,1,1), date(2027,2,8), date(2027,2,9), date(2027,3,26),
    date(2027,4,21), date(2027,5,1), date(2027,5,27), date(2027,9,7),
    date(2027,10,12), date(2027,11,2), date(2027,11,15), date(2027,11,20), date(2027,12,25),
    # 2028
    date(2028,1,1), date(2028,2,28), date(2028,2,29), date(2028,4,14),
    date(2028,4,21), date(2028,5,1), date(2028,6,15), date(2028,9,7),
    date(2028,10,12), date(2028,11,2), date(2028,11,15), date(2028,11,20), date(2028,12,25),
    # 2029
    date(2029,1,1), date(2029,2,12), date(2029,2,13), date(2029,3,30),
    date(2029,4,21), date(2029,5,1), date(2029,5,31), date(2029,9,7),
    date(2029,10,12), date(2029,11,2), date(2029,11,15), date(2029,11,20), date(2029,12,25),
    # 2030
    date(2030,1,1), date(2030,3,4), date(2030,3,5), date(2030,4,19),
    date(2030,4,21), date(2030,5,1), date(2030,6,20), date(2030,9,7),
    date(2030,10,12), date(2030,11,2), date(2030,11,15), date(2030,11,20), date(2030,12,25),
    # 2031
    date(2031,1,1), date(2031,2,24), date(2031,2,25), date(2031,4,11),
    date(2031,4,21), date(2031,5,1), date(2031,6,12), date(2031,9,7),
    date(2031,10,12), date(2031,11,2), date(2031,11,15), date(2031,11,20), date(2031,12,25),
    # 2032
    date(2032,1,1), date(2032,2,9), date(2032,2,10), date(2032,3,26),
    date(2032,4,21), date(2032,5,1), date(2032,5,27), date(2032,9,7),
    date(2032,10,12), date(2032,11,2), date(2032,11,15), date(2032,11,20), date(2032,12,25),
    # 2033
    date(2033,1,1), date(2033,2,28), date(2033,3,1), date(2033,4,15),
    date(2033,4,21), date(2033,5,1), date(2033,6,16), date(2033,9,7),
    date(2033,10,12), date(2033,11,2), date(2033,11,15), date(2033,11,20), date(2033,12,25),
    # 2034
    date(2034,1,1), date(2034,2,20), date(2034,2,21), date(2034,4,7),
    date(2034,4,21), date(2034,5,1), date(2034,6,8), date(2034,9,7),
    date(2034,10,12), date(2034,11,2), date(2034,11,15), date(2034,11,20), date(2034,12,25),
    # 2035
    date(2035,1,1), date(2035,2,5), date(2035,2,6), date(2035,3,23),
    date(2035,4,21), date(2035,5,1), date(2035,5,24), date(2035,9,7),
    date(2035,10,12), date(2035,11,2), date(2035,11,15), date(2035,11,20), date(2035,12,25),
    # 2036
    date(2036,1,1), date(2036,2,25), date(2036,2,26), date(2036,4,11),
    date(2036,4,21), date(2036,5,1), date(2036,6,12), date(2036,9,7),
    date(2036,10,12), date(2036,11,2), date(2036,11,15), date(2036,11,20), date(2036,12,25),
    # 2037
    date(2037,1,1), date(2037,2,16), date(2037,2,17), date(2037,4,3),
    date(2037,4,21), date(2037,5,1), date(2037,6,4), date(2037,9,7),
    date(2037,10,12), date(2037,11,2), date(2037,11,15), date(2037,11,20), date(2037,12,25),
    # 2038
    date(2038,1,1), date(2038,3,8), date(2038,3,9), date(2038,4,21),
    date(2038,4,23), date(2038,5,1), date(2038,6,24), date(2038,9,7),
    date(2038,10,12), date(2038,11,2), date(2038,11,15), date(2038,11,20), date(2038,12,25),
}


def is_du(d: date) -> bool:
    """Verifica se a data eh dia util (nao eh fds nem feriado ANBIMA)."""
    return d.weekday() < 5 and d not in FERIADOS_ANBIMA


def next_du(d: date) -> date:
    """Retorna a propria data se DU, ou o proximo DU."""
    while not is_du(d):
        d += timedelta(days=1)
    return d


def du_entre(d1: date, d2: date) -> int:
    """Dias uteis entre d1 e d2.

    Convencao ANBIMA: d1 (liquidacao) inclusive, d2 (vencimento) exclusive.
    Conta DUs onde d >= d1 e d < d2.
    """
    count = 0
    d = d1
    while d < d2:
        if is_du(d):
            count += 1
        d += timedelta(days=1)
    return count


def dc_entre(d1: date, d2: date) -> int:
    """Dias corridos entre d1 e d2."""
    return (d2 - d1).days


def first_du_of_month(year: int, month: int) -> date:
    """Primeiro dia util do mes (para DI1, DOL, DDI, FRC)."""
    return next_du(date(year, month, 1))


def default_liq_date(data_negociacao: date) -> date:
    """Data de liquidacao padrao = D+1 (proximo DU apos data de negociacao)."""
    return next_du(data_negociacao + timedelta(days=1))


def parse_ticker(instrumento: str, ticker: str):
    """Resolve ticker para data de vencimento.

    Aceita formatos: F32, DI1F32, Jan/32, N27, etc.
    
    TPF (LTN, NTN-F, LFT): vencimento = dia 1 do mes (fixo, mesmo se feriado).
    NTN-B: vencimento = dia 15 do mes (fixo).
    Derivativos (DI1, DOL, DDI, FRC, DAP): vencimento = 1o DU do mes.
    """
    ticker = ticker.strip().upper()
    month, year = None, None

    m1 = re.match(r"^(?:DI1|DAP|LTN|NTNF|NTNB|LFT|DOL|WDO|DDI|FRC)?([FGHJKMNQUVXZ])(\d{2,4})$", ticker, re.I)
    m2 = re.match(r"^(Jan|Fev|Mar|Abr|Mai|Jun|Jul|Ago|Set|Out|Nov|Dez)/?(\d{2,4})$", ticker, re.I)

    if m1:
        month = MONTH_CODES[m1.group(1).upper()]
        year = int(m1.group(2))
    elif m2:
        name = m2.group(1).capitalize()
        month = MONTH_NAMES.index(name)
        year = int(m2.group(2))
    else:
        return None

    if year < 100:
        year += 2000
    if not month or not year:
        return None

    if instrumento in ("LTN", "NTN-F", "LFT"):
        venc = date(year, month, 1)
    elif instrumento == "NTN-B":
        venc = date(year, month, 15)
    else:
        venc = first_du_of_month(year, month)

    label = f"{MONTH_NAMES[month]}/{year % 100:02d}"
    return {"date": venc, "label": label, "full": venc.strftime("%d/%m/%Y")}
