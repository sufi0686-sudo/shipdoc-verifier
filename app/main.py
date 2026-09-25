"""Web app + REST API.

Run locally:  uvicorn app.main:app --reload
Docs:         http://localhost:8000/docs
"""
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import llm
from .adapters import Attachment, Email
from .pipeline import process_email, to_submission

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

app = FastAPI(
    title="Shipping Document Verification System",
    description="Classifies shipping emails and compares Shipping Instructions against Bills of Lading.",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory stores (reset on restart). Swap for a database in production.
REVIEW_QUEUE: Dict[str, Dict] = {}
STATS = {"processed": 0, "mismatches": 0, "escalated": 0}


def _track(report: Dict) -> Dict:
    STATS["processed"] += 1
    STATS["mismatches"] += int(report["mismatch_found"])
    if report["needs_human_review"]:
        STATS["escalated"] += 1
        REVIEW_QUEUE[report["email_id"]] = {
            "report": report, "status": "open",
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
    return report


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_enabled": llm.enabled(), **STATS}


@app.get("/api/samples")
def samples():
    with open(os.path.join(ROOT, "data", "sample_inbox.json")) as fh:
        return json.load(fh)


@app.post("/api/process")
def process(email: Dict[str, Any] = Body(..., examples=[{
    "email_id": "EM-100", "subject": "Please compare SI vs BL",
    "body": "See attached", "attachments": [{"filename": "si.txt", "content": "Shipper: ..."}]}])):
    """Process one email given as JSON (attachments as text or base64)."""
    return _track(process_email(email))


@app.post("/api/process-upload")
async def process_upload(
    subject: str = Form(""),
    body: str = Form(""),
    email_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
):
    """Process one email with real file uploads (txt, PDF, DOCX, images)."""
    atts = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename} is larger than 15 MB")
        atts.append(Attachment(filename=f.filename or "upload", data=data))
    email = Email(email_id=email_id or f"WEB-{STATS['processed'] + 1:04d}",
                  subject=subject, body=body, attachments=atts)
    return _track(process_email(email))


@app.post("/api/batch")
def batch(payload: Any = Body(...)):
    """Process a list of emails (or {"emails": [...]}). Returns compact + full results."""
    records = payload.get("emails") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise HTTPException(422, 'Send a JSON list of emails or {"emails": [...]}')
    reports = [_track(process_email(r)) for r in records]
    categories: Dict[str, int] = {}
    for r in reports:
        categories[r["category"]] = categories.get(r["category"], 0) + 1
    return {
        "summary": {
            "total": len(reports),
            "mismatches": sum(r["mismatch_found"] for r in reports),
            "escalated": sum(r["needs_human_review"] for r in reports),
            "categories": categories,
            "avg_ms": round(sum(r["processing_ms"] for r in reports) / max(1, len(reports)), 1),
        },
        "results": [to_submission(r) for r in reports],
        "reports": reports,
    }


@app.post("/api/batch-upload")
async def batch_upload(file: UploadFile = File(...)):
    try:
        data = json.loads(await file.read())
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"File is not valid JSON: {exc}")
    return batch(data)


@app.get("/api/review-queue")
def review_queue(status: str = "open"):
    items = [dict(email_id=k, **v) for k, v in REVIEW_QUEUE.items() if status == "all" or v["status"] == status]
    return sorted(items, key=lambda x: x["queued_at"], reverse=True)


class Resolution(BaseModel):
    decision: str                   # "confirmed" | "overridden"
    category: Optional[str] = None  # corrected category, if overridden
    mismatch_found: Optional[bool] = None
    note: str = ""


@app.post("/api/review-queue/{email_id}/resolve")
def resolve(email_id: str, res: Resolution):
    item = REVIEW_QUEUE.get(email_id)
    if not item:
        raise HTTPException(404, f"No review item for {email_id}")
    report = item["report"]
    if res.category:
        report["category"] = res.category
    if res.mismatch_found is not None:
        report["mismatch_found"] = res.mismatch_found
    item.update(status="resolved", decision=res.decision, note=res.note,
                resolved_at=datetime.now(timezone.utc).isoformat())
    return {"email_id": email_id, "status": "resolved", "final": to_submission(report)}
