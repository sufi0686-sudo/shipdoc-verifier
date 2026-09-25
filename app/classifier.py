"""Weighted-rule email classifier.

Each category has regex signals with weights. Scores are summed over the
subject (counted double), body and attachment names, plus structural signals
(e.g. an SI *and* a BL are attached). Confidence combines how dominant the top
category is with how much evidence there is at all, so a weak or split vote
produces low confidence and the email is escalated.
"""
import re
from dataclasses import dataclass
from typing import Dict, List

RULES: Dict[str, List[tuple]] = {
    "doc_comparison": [
        (r"\bcompar(e|ison|ing)\b", 2.0),
        (r"\bcross[- ]?check", 2.0),
        (r"\bdiscrepanc", 2.0),
        (r"\bmismatch", 2.0),
        (r"\bverif(y|ication)\b", 1.5),
        (r"\bcheck\b.{0,25}\b(draft\s+)?(bl|b/l|bill of lading)\b", 2.0),
        (r"\bdraft\s+(bl|b/l|bill of lading)\b", 1.5),
        (r"\bagainst\s+(the\s+|our\s+)?(si|shipping instructions?)\b", 2.0),
        (r"\breconcil", 1.5),
        (r"\bbefore\s+(finali[sz]|releas|issu)", 1.0),
    ],
    "si_request": [
        (r"\b(send|submit|provide|share|forward|furnish)\b.{0,40}\b(si|shipping instructions?)\b", 3.0),
        (r"\bsi\s+(cut[- ]?off|deadline|submission)\b", 2.5),
        (r"\b(cut[- ]?off|deadline)\b", 1.0),
        (r"\bshipping instructions?\b", 0.5),
        (r"\bbooking\s+(no|number|ref|confirmation)", 0.5),
    ],
    "invoice": [
        (r"\binvoice", 3.0),
        (r"\bpayment\b", 1.5),
        (r"\bamount\s+due\b", 2.0),
        (r"\b(remit|remittance)\b", 1.5),
        (r"\bfreight\s+charges?\b", 1.0),
        (r"\bdebit\s+note\b", 2.0),
        (r"\b(usd|myr|rm|eur|sgd)\s?[\d,]+(\.\d+)?", 1.0),
        (r"\bdue\s+date\b", 1.0),
        (r"\bbank\s+(details|account)\b", 1.0),
    ],
    "general_update": [
        (r"\b(eta|etd|ata|atd)\b", 1.5),
        (r"\bvessel\b", 1.0),
        (r"\bschedule\b", 1.0),
        (r"\bdelay(ed|s)?\b", 1.5),
        (r"\bupdate\b", 1.0),
        (r"\b(departed|arrived|berthed|sailed|discharged)\b", 1.5),
        (r"\broll(ed)?[- ]?over\b", 1.5),
        (r"\bcongestion\b", 1.5),
        (r"\b(holiday|advisory|notice)\b", 1.0),
    ],
    "spam": [
        (r"\bunsubscribe\b", 2.0),
        (r"\b(winner|you('ve)? won|lottery|prize)\b", 2.5),
        (r"\bclick\s+here\b", 2.0),
        (r"\b(free|limited[- ]time)\s+(offer|gift|trial)\b", 2.0),
        (r"\b(crypto|bitcoin|investment opportunity)\b", 2.0),
        (r"\bcongratulations\b", 1.5),
        (r"\b(act now|claim (your|now))\b", 1.5),
        (r"\b(casino|loan approved|viagra)\b", 3.0),
    ],
}

_COMPILED = {c: [(re.compile(p, re.I | re.S), w) for p, w in rules] for c, rules in RULES.items()}


@dataclass
class Classification:
    category: str
    confidence: float
    scores: Dict[str, float]
    source: str = "rules"


def classify(subject: str, body: str, doc_types: List[str], attachment_names: List[str]) -> Classification:
    scores = {c: 0.0 for c in RULES}
    names = " ".join(attachment_names)
    for cat, rules in _COMPILED.items():
        for rx, w in rules:
            if rx.search(subject or ""):
                scores[cat] += w * 2  # subject lines are strong signals
            if rx.search(body or ""):
                scores[cat] += w
            if rx.search(names):
                scores[cat] += w * 0.5

    # Structural signals from the attachments themselves.
    if "SI" in doc_types and "BL" in doc_types:
        scores["doc_comparison"] += 5.0
    elif "BL" in doc_types:
        scores["doc_comparison"] += 1.5

    total = sum(scores.values())
    if total == 0:
        return Classification("general_update", 0.0, scores)
    top_cat = max(scores, key=scores.get)
    top = scores[top_cat]
    share = top / total                 # how dominant the winner is
    strength = min(1.0, top / 4.0)      # how much evidence there is
    confidence = round(share * strength, 3)
    return Classification(top_cat, confidence, {k: round(v, 2) for k, v in scores.items()})
