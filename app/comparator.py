"""Compare SI vs BL field by field.

Status per field:
  match      values are equal after normalisation
  mismatch   values clearly differ (or present on one side only)
  uncertain  close but not identical (e.g. a possible typo) -> human review
  not_found  field missing from both documents -> human review
"""
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from .config import (FIELD_LABELS, FIELDS, PARTY_UNCERTAIN_THRESHOLD,
                     WEIGHT_TOLERANCE_KG)
from .normalizer import (normalize_container_count, normalize_party,
                         normalize_port, normalize_weight_kg)

NORMALIZERS = {
    "shipper": normalize_party,
    "consignee": normalize_party,
    "notify_party": normalize_party,
    "port_of_loading": normalize_port,
    "port_of_discharge": normalize_port,
    "container_count": normalize_container_count,
    "gross_weight_kg": normalize_weight_kg,
}


def _similarity(a: str, b: str) -> float:
    direct = SequenceMatcher(None, a, b).ratio()
    token_sorted = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()
    return round(max(direct, token_sorted), 3)


def compare_field(field: str, si_raw: Optional[str], bl_raw: Optional[str]) -> Dict:
    res = {
        "field": field, "label": FIELD_LABELS[field],
        "si": si_raw, "bl": bl_raw,
        "si_normalized": None, "bl_normalized": None,
        "status": None, "similarity": None, "note": "",
    }
    if si_raw is None and bl_raw is None:
        res.update(status="not_found", note="Not found in either document")
        return res
    if si_raw is None or bl_raw is None:
        side = "SI" if si_raw is None else "BL"
        res.update(status="mismatch", note=f"Missing from {side}")
        return res

    norm = NORMALIZERS[field]
    si_n, bl_n = norm(si_raw), norm(bl_raw)
    res["si_normalized"], res["bl_normalized"] = si_n, bl_n

    if si_n is None or bl_n is None:
        res.update(status="uncertain", note="Value could not be parsed")
        return res

    if field == "container_count":
        ok = si_n == bl_n
        res.update(status="match" if ok else "mismatch", similarity=1.0 if ok else 0.0)
    elif field == "gross_weight_kg":
        diff = abs(si_n - bl_n)
        ok = diff <= WEIGHT_TOLERANCE_KG
        res.update(status="match" if ok else "mismatch", similarity=1.0 if ok else 0.0)
        if not ok:
            res["note"] = f"Differs by {diff:,.2f} kg"
    else:
        if si_n == bl_n:
            res.update(status="match", similarity=1.0)
        else:
            sim = _similarity(si_n, bl_n)
            if sim >= PARTY_UNCERTAIN_THRESHOLD:
                res.update(status="uncertain", similarity=sim, note="Very similar - possible typo")
            else:
                res.update(status="mismatch", similarity=sim)
    return res


def compare_documents(si_fields: Dict[str, Optional[str]], bl_fields: Dict[str, Optional[str]]) -> List[Dict]:
    return [compare_field(f, si_fields.get(f), bl_fields.get(f)) for f in FIELDS]
