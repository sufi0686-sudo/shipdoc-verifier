"""End-to-end pipeline: email in -> JSON report out.

  1. Read attachments (txt / PDF / Word / OCR)      parsers.py
  2. Detect which document is the SI and the BL      parsers.py
  3. Classify the email                              classifier.py (+ llm.py)
  4. Extract the 7 fields from SI and BL             extractor.py  (+ llm.py)
  5. Compare field by field                          comparator.py
  6. Decide on human escalation                      escalation.py
  7. Build the report                                this file
"""
import re
import time
from typing import Any, Dict, List, Optional

from . import llm
from .adapters import coerce_email
from .classifier import classify
from .comparator import compare_documents
from .config import (CLASSIFY_CONFIDENCE_THRESHOLD, FIELD_LABELS, FIELDS,
                     INCLUDE_REVIEW_FLAG, MISMATCH_FORMAT,
                     UNCERTAIN_COUNTS_AS_MISMATCH)
from .escalation import review_reasons
from .extractor import extract_fields, split_inline_documents
from .parsers import detect_doc_type, extract_text

_SAME_AS = re.compile(r"^\s*same\s+as\s+(the\s+)?consignee", re.I)


def _assign_si_bl(docs: List[Dict]) -> Dict[str, Optional[Dict]]:
    si = next((d for d in docs if d["detected_type"] == "SI"), None)
    bl = next((d for d in docs if d["detected_type"] == "BL"), None)
    unknown = [d for d in docs if d["detected_type"] is None and d["text"].strip()]
    # Assign by elimination when one document is unlabelled.
    if si and not bl and unknown:
        bl = unknown[0]
        bl["detected_type"] = "BL"
    elif bl and not si and unknown:
        si = unknown[0]
        si["detected_type"] = "SI"
    return {"SI": si, "BL": bl}


def _extract(text: str, notes: List[str], label: str) -> Dict[str, Optional[str]]:
    fields = extract_fields(text)
    missing = [f for f in FIELDS if fields[f] is None]
    if len(missing) >= 2 and llm.enabled():
        filled = llm.extract(text)
        if filled:
            for f in missing:
                if filled.get(f):
                    fields[f] = filled[f]
            notes.append(f"LLM filled {label} fields: {', '.join(f for f in missing if fields[f])}")
    if fields.get("notify_party") and _SAME_AS.match(fields["notify_party"]):
        fields["notify_party"] = fields.get("consignee") or fields["notify_party"]
    return fields


def _format_mismatches(rows: List[Dict]) -> Any:
    flagged = [r for r in rows if r["status"] == "mismatch"
               or (r["status"] == "uncertain" and UNCERTAIN_COUNTS_AS_MISMATCH)]
    def pair(r):
        return f"SI: {r['si'] if r['si'] is not None else 'missing'} / BL: {r['bl'] if r['bl'] is not None else 'missing'}"
    if MISMATCH_FORMAT == "list":
        return [r["field"] for r in flagged]
    if MISMATCH_FORMAT == "string":
        return "; ".join(f"{FIELD_LABELS[r['field']]} ({pair(r)})" for r in flagged)
    return {r["field"]: pair(r) for r in flagged}


def process_email(raw: Any) -> Dict:
    started = time.perf_counter()
    email = coerce_email(raw)
    notes: List[str] = []
    read_errors: List[str] = []

    # 1-2. Read attachments and work out which is which.
    docs = []
    for att in email.attachments:
        text, note = extract_text(att)
        if note == "ocr_used":
            notes.append(f"OCR used for {att.filename}")
        elif note:
            read_errors.append(note)
        docs.append({"filename": att.filename, "text": text,
                     "detected_type": detect_doc_type(att.filename, text)})
    if not any(d["detected_type"] for d in docs):
        for kind, text in split_inline_documents(email.body).items():
            docs.append({"filename": f"(email body) {kind}", "text": text, "detected_type": kind})
            notes.append(f"{kind} found in email body")

    # 3. Classify.
    cls = classify(email.subject, email.body,
                   [d["detected_type"] for d in docs], [d["filename"] for d in docs])
    category, confidence, source = cls.category, cls.confidence, "rules"
    if confidence < CLASSIFY_CONFIDENCE_THRESHOLD and llm.enabled():
        second = llm.classify(email.subject, email.body, [d["filename"] for d in docs])
        if second:
            if second["category"] == category:
                confidence = max(confidence, second["confidence"])
                source = "rules+llm"
            elif second["confidence"] > confidence:
                category, confidence, source = second["category"], second["confidence"], "llm"

    # 4-5. Extract and compare (only for comparison requests).
    comparison, si_fields, bl_fields = None, None, None
    pair = _assign_si_bl(docs) if category == "doc_comparison" else {"SI": None, "BL": None}
    if category == "doc_comparison" and pair["SI"] and pair["BL"]:
        si_fields = _extract(pair["SI"]["text"], notes, "SI")
        bl_fields = _extract(pair["BL"]["text"], notes, "BL")
        comparison = compare_documents(si_fields, bl_fields)

    # 6. Escalation.
    reasons = review_reasons(category, confidence, bool(pair["SI"]), bool(pair["BL"]),
                             comparison, read_errors)

    # 7. Report.
    mismatched = _format_mismatches(comparison) if comparison else ({} if MISMATCH_FORMAT == "dict" else [] if MISMATCH_FORMAT == "list" else "")
    return {
        "email_id": email.email_id,
        "category": category,
        "mismatch_found": bool(mismatched),
        "mismatched_fields": mismatched,
        "needs_human_review": bool(reasons),
        "review_reasons": reasons,
        "confidence": round(confidence, 3),
        "classified_by": source,
        "category_scores": cls.scores,
        "subject": email.subject,
        "documents": [{"filename": d["filename"], "detected_type": d["detected_type"],
                       "characters": len(d["text"])} for d in docs],
        "field_comparison": comparison,
        "notes": notes,
        "processing_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def to_submission(report: Dict) -> Dict:
    """The compact JSON the self-evaluation endpoint expects."""
    out = {k: report[k] for k in ("email_id", "category", "mismatch_found", "mismatched_fields")}
    if INCLUDE_REVIEW_FLAG:
        out["needs_human_review"] = report["needs_human_review"]
    return out
