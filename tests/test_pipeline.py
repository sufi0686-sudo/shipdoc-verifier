"""Run with:  pytest -q"""
import base64
import json
import os

from fastapi.testclient import TestClient

from app.extractor import extract_fields
from app.main import app
from app.normalizer import (normalize_container_count, normalize_party,
                            normalize_port, normalize_weight_kg)
from app.pipeline import process_email, to_submission

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = json.load(open(os.path.join(ROOT, "data", "sample_inbox.json")))


# ---------- normalisers ----------
def test_party_names_ignore_punctuation_and_legal_suffixes():
    assert normalize_party("Sinar Palm Oil Sdn. Bhd.") == normalize_party("SINAR PALM OIL SDN BHD")
    assert normalize_party("Rotterdam Food Imports B.V.") == normalize_party("ROTTERDAM FOOD IMPORTS BV")


def test_ports_resolve_codes_and_spellings():
    assert normalize_port("Port Kelang (MYPKG)") == normalize_port("Port Klang, Malaysia") == "PORT KLANG"
    assert normalize_port("NLRTM") == normalize_port("Rotterdam, Netherlands") == "ROTTERDAM"


def test_container_counts():
    assert normalize_container_count("2 x 40HC") == 2
    assert normalize_container_count("TWO (2)") == 2
    assert normalize_container_count("2 x 20GP + 1 x 40HC") == 3
    assert normalize_container_count("Three") == 3


def test_weights_and_units():
    assert normalize_weight_kg("42,500.00") == 42500
    assert normalize_weight_kg("42500 KGS") == 42500
    assert normalize_weight_kg("12.500,50 kg") == 12500.5
    assert normalize_weight_kg("25 MT") == 25000
    assert abs(normalize_weight_kg("22,046 LBS") - 10000) < 1


# ---------- extractor ----------
def test_extracts_varied_layouts():
    text = "1. Exporter: ACME Sdn Bhd\n| POD | Shenzhen |\nCONSIGNEE\nBUYER LTD\nG.W.: 1,000 kg"
    f = extract_fields(text)
    assert f["shipper"] == "ACME Sdn Bhd"
    assert f["port_of_discharge"] == "Shenzhen"
    assert f["consignee"] == "BUYER LTD"
    assert f["gross_weight_kg"] == "1,000 kg"


# ---------- full pipeline on the labelled sample inbox ----------
def test_sample_inbox_accuracy():
    for email in SAMPLES:
        exp = email["_expected"]
        rep = process_email(email)
        assert rep["category"] == exp["category"], email["email_id"]
        assert rep["mismatch_found"] == exp["mismatch_found"], email["email_id"]
        assert set(rep["mismatched_fields"]) == set(exp["mismatched_fields"]), email["email_id"]
        if "needs_human_review" in exp:
            assert rep["needs_human_review"] == exp["needs_human_review"]


def test_submission_shape():
    out = to_submission(process_email(SAMPLES[1]))
    assert out["mismatched_fields"]["container_count"] == "SI: 3 / BL: 4 x 40' HC"
    assert set(out) >= {"email_id", "category", "mismatch_found", "mismatched_fields"}


def test_pdf_and_docx_attachments():
    def b64(name):
        return base64.b64encode(open(os.path.join(ROOT, "data", "samples", name), "rb").read()).decode()
    rep = process_email({
        "id": "ADV-1", "subject": "Please compare SI and BL",
        "attachments": [{"filename": "SI_sample.docx", "content_base64": b64("SI_sample.docx")},
                        {"filename": "BL_sample.pdf", "content_base64": b64("BL_sample.pdf")}],
    })
    assert rep["category"] == "doc_comparison"
    assert set(rep["mismatched_fields"]) == {"container_count", "gross_weight_kg"}


# ---------- API ----------
def test_api_endpoints():
    c = TestClient(app)
    assert c.get("/api/health").json()["status"] == "ok"
    batch = c.post("/api/batch", json=SAMPLES).json()
    assert batch["summary"]["total"] == len(SAMPLES)
    queue = c.get("/api/review-queue").json()
    assert queue
    r = c.post(f"/api/review-queue/{queue[0]['email_id']}/resolve", json={"decision": "confirmed"})
    assert r.json()["status"] == "resolved"
    up = c.post("/api/process-upload", data={"subject": "compare SI vs BL"},
                files=[("files", ("si.txt", open(os.path.join(ROOT, "data/samples/SI_sample.txt"), "rb"))),
                       ("files", ("bl.txt", open(os.path.join(ROOT, "data/samples/BL_sample.txt"), "rb")))])
    assert up.json()["mismatch_found"] is True
