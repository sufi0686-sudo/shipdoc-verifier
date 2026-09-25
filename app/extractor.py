"""Pull the 7 key fields out of SI / BL text.

Handles the layouts seen in real shipping documents:
  * "Label: value" / "Label - value" / "Label = value" on one line
  * "| Label | value |" table rows (Markdown, Word and PDF tables)
  * a label on its own line with the value on the following line(s)
  * numbered or bulleted labels ("3. Consignee:")
  * label variations (POL, Exporter, G.W., No. of Containers, ...)
"""
import re
from typing import Dict, List, Optional, Tuple

from .config import FIELD_ALIASES, FIELDS

_PREFIX = r"^\s*(?:[|\-*\u2022>#]+\s*)?(?:\d{1,2}[.)]\s*)?"
_SUFFIX = r"(?![a-z0-9])\s*(?:\([^)]*\))?\s*"
_EMPTY = {"", "-", "--", "n/a", "na", "nil", "none", "tbc", "tba"}


def _build_patterns() -> List[Tuple[str, re.Pattern, re.Pattern]]:
    pairs = [(alias, field) for field, aliases in FIELD_ALIASES.items() for alias in aliases]
    pairs.sort(key=lambda p: -len(p[0]))  # longest alias wins ("notify party" before "notify")
    out = []
    for alias, field in pairs:
        a = re.escape(alias).replace(r"\ ", r"\s+")
        same_line = re.compile(_PREFIX + a + _SUFFIX + r"(?:[:|=\t]|\s-\s|\s{2,})\s*(.*)$", re.I)
        label_only = re.compile(_PREFIX + a + _SUFFIX + r":?\s*\|?\s*$", re.I)
        out.append((field, same_line, label_only))
    return out


_PATTERNS = _build_patterns()


def _match_label(line: str) -> Optional[Tuple[str, Optional[str]]]:
    """Return (field, value_or_None) if the line starts with a known label."""
    for field, same_line, label_only in _PATTERNS:
        if label_only.match(line):
            return field, None
        m = same_line.match(line)
        if m:
            value = m.group(1).strip().strip("|").strip()
            return field, value or None
    return None


def _clean_value(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = re.sub(r"\s+\|\s*$", "", v).strip()
    return None if v.lower() in _EMPTY else v


def extract_fields(text: str) -> Dict[str, Optional[str]]:
    """Return {field: raw value or None}. For party fields the value is the
    first line (the company name); following address lines are ignored."""
    fields: Dict[str, Optional[str]] = {f: None for f in FIELDS}
    lines = text.replace("\r", "").split("\n")
    i = 0
    while i < len(lines):
        hit = _match_label(lines[i])
        if not hit:
            i += 1
            continue
        field, value = hit
        if value is None:
            # Value lives on the next non-empty line that is not another label.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and not _match_label(lines[j]):
                value = lines[j].strip().strip("|").strip()
                i = j
        if fields[field] is None:
            fields[field] = _clean_value(value)
        i += 1
    return fields


def split_inline_documents(body: str) -> Dict[str, str]:
    """Some senders paste SI and BL into the email body instead of attaching.
    Split the body on the two document headings if both are present."""
    si = re.search(r"^.*shipping\s+instructions?.*$", body, re.I | re.M)
    bl = re.search(r"^.*bill\s+of\s+lading.*$", body, re.I | re.M)
    if not si or not bl:
        return {}
    if si.start() < bl.start():
        return {"SI": body[si.start():bl.start()], "BL": body[bl.start():]}
    return {"BL": body[bl.start():si.start()], "SI": body[si.start():]}
