"""Optional LLM second opinion (hybrid mode).

The rules engine handles the clear cases for free and in milliseconds. Only
low-confidence emails, or documents where regex extraction missed fields, are
sent to the LLM. If ANTHROPIC_API_KEY is not set, every function here returns
None and the system runs fully offline.
"""
import json
import re
from typing import Dict, Optional

import requests

from .config import CATEGORIES, FIELDS, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT_S

API_URL = "https://api.anthropic.com/v1/messages"


def enabled() -> bool:
    return bool(LLM_API_KEY)


def _ask(prompt: str, max_tokens: int = 400) -> Optional[str]:
    if not enabled():
        return None
    try:
        r = requests.post(
            API_URL,
            headers={
                "x-api-key": LLM_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": LLM_MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=LLM_TIMEOUT_S,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    except Exception:
        return None  # never let the optional LLM break the pipeline


def _json(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group()) if m else None
    except json.JSONDecodeError:
        return None


def classify(subject: str, body: str, attachment_names) -> Optional[Dict]:
    prompt = (
        "You classify emails for a shipping/freight company.\n"
        f"Categories: {', '.join(CATEGORIES)}.\n"
        "doc_comparison = the sender wants a Shipping Instruction (SI) checked against a Bill of Lading (BL).\n"
        "si_request = someone asks for shipping instructions to be sent.\n"
        'Reply with JSON only: {"category": "...", "confidence": 0.0-1.0}\n\n'
        f"Subject: {subject}\nAttachments: {', '.join(attachment_names) or 'none'}\n"
        f"Body:\n{body[:3000]}"
    )
    data = _json(_ask(prompt, 100))
    if data and data.get("category") in CATEGORIES:
        return {"category": data["category"], "confidence": float(data.get("confidence", 0.5))}
    return None


def extract(text: str) -> Optional[Dict[str, Optional[str]]]:
    prompt = (
        "Extract these fields from the shipping document below. For parties give the "
        "company name only. Use null if a field is absent. Do not guess.\n"
        f"Fields: {', '.join(FIELDS)}\nReply with JSON only.\n\n{text[:6000]}"
    )
    data = _json(_ask(prompt, 500))
    if not data:
        return None
    return {f: (str(data[f]) if data.get(f) not in (None, "") else None) for f in FIELDS}
