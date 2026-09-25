"""Decide when a human must look at an email, and explain why.

The principle: the system may say "match" only when it is sure. Anything it is
unsure about goes to a person with a specific, actionable reason.
"""
from typing import Dict, List, Optional

from .config import CLASSIFY_CONFIDENCE_THRESHOLD


def review_reasons(
    category: str,
    confidence: float,
    si_found: bool,
    bl_found: bool,
    comparison: Optional[List[Dict]],
    read_errors: List[str],
) -> List[str]:
    reasons: List[str] = []
    if confidence < CLASSIFY_CONFIDENCE_THRESHOLD:
        reasons.append(f"Low classification confidence ({confidence:.0%})")
    reasons.extend(read_errors)

    if category != "doc_comparison":
        return reasons

    if not si_found:
        reasons.append("Shipping Instruction not found in the email")
    if not bl_found:
        reasons.append("Bill of Lading not found in the email")

    for row in comparison or []:
        if row["status"] == "uncertain":
            reasons.append(f"{row['label']}: {row['note'] or 'needs a human check'}")
        elif row["status"] == "not_found":
            reasons.append(f"{row['label']}: not found in either document")

    if comparison:
        missing = sum(1 for r in comparison if r["si"] is None or r["bl"] is None)
        if missing >= 3:
            reasons.append(f"{missing} of 7 fields could not be extracted - check document format")
    return reasons
