"""Turn whatever the organiser's loader.py returns into one Email shape.

The exact record format of the inbox is not known in advance, so this module
accepts dicts, dataclasses, pydantic models, file paths and base64 content,
and tolerates many different key names.
"""
import base64
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

BINARY_EXT = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class Attachment:
    filename: str
    text: Optional[str] = None     # already-decoded text (basic stage)
    data: Optional[bytes] = None   # raw bytes (PDF/Word/image, advanced stage)


@dataclass
class Email:
    email_id: str
    subject: str = ""
    body: str = ""
    sender: str = ""
    attachments: List[Attachment] = field(default_factory=list)


def _as_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "dict", "_asdict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    raise TypeError(f"Cannot read email record of type {type(obj).__name__}")


def _first(d: dict, *keys, default=None):
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k in lower and lower[k] not in (None, ""):
            return lower[k]
    return default


def _coerce_attachment(item: Any) -> Attachment:
    if isinstance(item, Attachment):
        return item
    if isinstance(item, str):
        if os.path.isfile(item):
            with open(item, "rb") as fh:
                return Attachment(os.path.basename(item), data=fh.read())
        return Attachment("attachment.txt", text=item)

    d = _as_dict(item)
    name = str(_first(d, "filename", "name", "file_name", "title", default="attachment.txt"))
    ext = os.path.splitext(name.lower())[1]

    path = _first(d, "path", "filepath", "file_path")
    if path and os.path.isfile(str(path)):
        with open(str(path), "rb") as fh:
            fname = name if name != "attachment.txt" else os.path.basename(str(path))
            return Attachment(fname, data=fh.read())

    b64 = _first(d, "content_base64", "base64", "data_base64", "b64", "content_b64")
    if b64:
        return Attachment(name, data=base64.b64decode(b64))

    content = _first(d, "text", "content", "data", "body")
    if isinstance(content, (bytes, bytearray)):
        return Attachment(name, data=bytes(content))
    if isinstance(content, str):
        if ext in BINARY_EXT:
            try:
                return Attachment(name, data=base64.b64decode(content, validate=True))
            except Exception:
                pass
        return Attachment(name, text=content)
    return Attachment(name, text="")


def coerce_email(raw: Any) -> Email:
    if isinstance(raw, Email):
        return raw
    d = _as_dict(raw)
    email_id = _first(d, "email_id", "id", "message_id", "uid", "record_id")
    atts = _first(d, "attachments", "files", "documents", default=[]) or []
    if isinstance(atts, dict):  # {"si.txt": "...", "bl.txt": "..."}
        atts = [{"filename": k, "content": v} for k, v in atts.items()]
    return Email(
        email_id=str(email_id) if email_id is not None else uuid.uuid4().hex[:10],
        subject=str(_first(d, "subject", "title", default="")),
        body=str(_first(d, "body", "text", "content", "message", "body_text", default="")),
        sender=str(_first(d, "from", "sender", "from_address", default="")),
        attachments=[_coerce_attachment(a) for a in atts],
    )
