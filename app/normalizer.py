"""Normalise messy values so that equal things compare equal.

  "Sinar Palm Oil Sdn. Bhd."  == "SINAR PALM OIL SDN BHD"
  "Port Kelang (MYPKG)"       == "Port Klang, Malaysia"
  "TWO (2) x 40' HC"          == "2"
  "22,046 LBS"                == "10,000 KGS"
"""
import re
import unicodedata
from typing import Optional

LEGAL_TOKENS = {
    "SDN", "BHD", "BERHAD", "LTD", "LIMITED", "CO", "COMPANY", "INC",
    "INCORPORATED", "CORP", "CORPORATION", "LLC", "LLP", "PTE", "PLC",
    "GMBH", "AG", "SA", "BV", "NV", "PT", "TBK", "THE", "AND",
}

# Canonical port name -> spellings, UN/LOCODEs and common nicknames.
PORT_ALIASES = {
    "PORT KLANG": ["PORT KELANG", "KLANG", "MYPKG", "WESTPORTS", "NORTHPORT", "PKG"],
    "TANJUNG PELEPAS": ["MYTPP", "PTP", "TANJONG PELEPAS"],
    "PENANG": ["MYPEN", "GEORGE TOWN", "PULAU PINANG"],
    "PASIR GUDANG": ["MYPGU", "JOHOR PORT"],
    "SINGAPORE": ["SGSIN", "SIN"],
    "ROTTERDAM": ["NLRTM", "RTM"],
    "HAMBURG": ["DEHAM"],
    "ANTWERP": ["BEANR", "ANTWERPEN"],
    "SHANGHAI": ["CNSHA"],
    "NINGBO": ["CNNGB", "NINGBO ZHOUSHAN"],
    "SHENZHEN": ["CNSZX", "YANTIAN", "CNYTN"],
    "QINGDAO": ["CNTAO"],
    "HONG KONG": ["HKHKG"],
    "BUSAN": ["KRPUS", "PUSAN"],
    "TOKYO": ["JPTYO"],
    "JEBEL ALI": ["AEJEA"],
    "LOS ANGELES": ["USLAX"],
    "LONG BEACH": ["USLGB"],
    "NEW YORK": ["USNYC"],
    "JAKARTA": ["IDJKT", "TANJUNG PRIOK"],
    "LAEM CHABANG": ["THLCH"],
    "HO CHI MINH": ["VNSGN", "SAIGON", "CAT LAI"],
    "CHENNAI": ["INMAA"],
    "NHAVA SHEVA": ["INNSA", "JNPT"],
    "SYDNEY": ["AUSYD"],
    "FELIXSTOWE": ["GBFXT"],
}
_PORT_LOOKUP = {}
for canon, aliases in PORT_ALIASES.items():
    _PORT_LOOKUP[canon] = canon
    for a in aliases:
        _PORT_LOOKUP[a] = canon

COUNTRIES = {
    "MALAYSIA", "CHINA", "NETHERLANDS", "THE NETHERLANDS", "GERMANY", "BELGIUM",
    "USA", "US", "UNITED STATES", "KOREA", "SOUTH KOREA", "JAPAN", "UAE",
    "INDIA", "VIETNAM", "THAILAND", "INDONESIA", "AUSTRALIA", "UK",
    "UNITED KINGDOM", "PRC",
}

NUMBER_WORDS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7,
    "EIGHT": 8, "NINE": 9, "TEN": 10, "ELEVEN": 11, "TWELVE": 12, "THIRTEEN": 13,
    "FOURTEEN": 14, "FIFTEEN": 15, "SIXTEEN": 16, "SEVENTEEN": 17,
    "EIGHTEEN": 18, "NINETEEN": 19, "TWENTY": 20,
}


def _basic(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"[.']", "", s)            # B.V. -> BV, SDN. -> SDN
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_party(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    first = v.strip().split("\n")[0]
    cleaned = _basic(first)
    core = " ".join(t for t in cleaned.split() if t not in LEGAL_TOKENS)
    return core or cleaned or None


def normalize_port(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    raw = v.strip().split("\n")[0]
    candidates = [raw, re.split(r"[,/(]", raw)[0]]
    candidates += re.findall(r"\(([^)]*)\)", raw)          # codes in brackets
    for cand in candidates:
        c = _basic(cand)
        c = re.sub(r"^(PORT OF|SEAPORT OF)\s+", "", c)
        for country in sorted(COUNTRIES, key=len, reverse=True):
            if c.endswith(" " + country):
                c = c[: -len(country) - 1].strip()
        if c in _PORT_LOOKUP:
            return _PORT_LOOKUP[c]
    fallback = re.sub(r"^(PORT OF|SEAPORT OF)\s+", "", _basic(candidates[1]))
    return fallback or None


def normalize_container_count(v: Optional[str]) -> Optional[int]:
    if not v:
        return None
    s = v.upper()
    s = re.sub(r"\(\s*[A-Z ]+\s*\)", " ", s)  # "3 (THREE)" -> "3"
    # "2 x 20GP + 1 x 40HC" -> 3
    multi = re.findall(r"(\d+)\s*[X\u00d7*]\s*\d{2}", s)
    if multi:
        return sum(int(n) for n in multi)
    m = re.search(r"\d+", s)
    if m:
        return int(m.group())
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", s):
            return n
    return None


_UNIT_TO_KG = {
    "KG": 1.0, "KGS": 1.0, "KILO": 1.0, "KILOS": 1.0, "KILOGRAM": 1.0, "KILOGRAMS": 1.0,
    "LB": 0.45359237, "LBS": 0.45359237, "POUND": 0.45359237, "POUNDS": 0.45359237,
    "MT": 1000.0, "TONNE": 1000.0, "TONNES": 1000.0, "TON": 1000.0, "TONS": 1000.0,
    "METRIC TON": 1000.0, "METRIC TONS": 1000.0, "T": 1000.0,
}


def _parse_number(num: str, tonnes: bool) -> Optional[float]:
    n = num.replace(" ", "").replace("'", "")
    if not n:
        return None
    if "," in n and "." in n:
        if n.rfind(",") > n.rfind("."):     # 12.500,50 (European)
            n = n.replace(".", "").replace(",", ".")
        else:                                # 12,500.50
            n = n.replace(",", "")
    elif "," in n:
        n = n.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", n) else n.replace(",", ".")
    elif "." in n and not tonnes and re.fullmatch(r"\d{1,3}(\.\d{3})+", n):
        n = n.replace(".", "")               # 12.500 kg (European thousands)
    try:
        return float(n)
    except ValueError:
        return None


def normalize_weight_kg(v: Optional[str]) -> Optional[float]:
    if not v:
        return None
    s = v.upper()
    m = re.search(
        r"(\d[\d.,' ]*\d|\d)\s*(METRIC TONS?|TONNES?|TONS?|MT|KILOGRAMS?|KILOS?|KGS?|POUNDS?|LBS?|T)?(?![A-Z])",
        s,
    )
    if not m:
        return None
    unit = (m.group(2) or "KG").strip()
    factor = _UNIT_TO_KG.get(unit, 1.0)
    value = _parse_number(m.group(1), tonnes=factor == 1000.0)
    return None if value is None else round(value * factor, 2)
