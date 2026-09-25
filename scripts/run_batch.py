"""Process a whole inbox, save the JSON results, and optionally submit them.

Usage
  python scripts/run_batch.py                          # uses loader.py if present, else sample data
  python scripts/run_batch.py --source data/sample_inbox.json
  python scripts/run_batch.py --submit                 # POST to $EVAL_URL

Put the organiser's loader.py in the project root. This script looks for a
loader function by common names; if yours is different, pass --loader-fn NAME.
"""
import argparse
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.pipeline import process_email, to_submission  # noqa: E402

LOADER_FN_NAMES = ["load_inbox", "load_emails", "load_records", "load_all",
                   "get_emails", "read_inbox", "load"]


def load_records(source=None, loader_fn=None):
    if source and source.endswith(".json"):
        with open(source) as fh:
            data = json.load(fh)
        return data.get("emails", data) if isinstance(data, dict) else data
    try:
        loader = importlib.import_module("loader")
    except ImportError:
        print("loader.py not found - using data/sample_inbox.json")
        return load_records(os.path.join(ROOT, "data", "sample_inbox.json"))
    names = [loader_fn] if loader_fn else LOADER_FN_NAMES
    for name in names:
        fn = getattr(loader, name, None)
        if callable(fn):
            try:
                records = fn() if source is None else fn(source)
            except TypeError:
                records = fn(source)
            print(f"Loaded records with loader.{name}()")
            if isinstance(records, dict):
                records = records.get("emails") or list(records.values())
            return list(records)
    raise SystemExit(f"No loader function found in loader.py. Tried: {names}. Use --loader-fn.")


def local_score(records, reports):
    """Score against "_expected" blocks if the records carry them."""
    rows = [(r.get("_expected"), rep) for r, rep in zip(records, reports) if isinstance(r, dict) and r.get("_expected")]
    if not rows:
        return
    cat = sum(e["category"] == rep["category"] for e, rep in rows)
    mm = sum(e["mismatch_found"] == rep["mismatch_found"] for e, rep in rows)
    fields = sum(
        set(e.get("mismatched_fields", [])) == set(rep["mismatched_fields"] if isinstance(rep["mismatched_fields"], (list, dict)) else [])
        for e, rep in rows
    )
    n = len(rows)
    print(f"\nLocal accuracy on {n} labelled emails")
    print(f"  category        {cat}/{n}")
    print(f"  mismatch_found  {mm}/{n}")
    print(f"  mismatched set  {fields}/{n}")
    for e, rep in rows:
        if e["category"] != rep["category"] or e["mismatch_found"] != rep["mismatch_found"]:
            print(f"  MISS {rep['email_id']}: expected {e['category']}/{e['mismatch_found']}, "
                  f"got {rep['category']}/{rep['mismatch_found']}")


def submit(results):
    import requests
    url = os.getenv("EVAL_URL")
    if not url:
        raise SystemExit("Set EVAL_URL (and EVAL_TOKEN / TEAM_ID if required) first.")
    headers = {"Content-Type": "application/json"}
    if os.getenv("EVAL_TOKEN"):
        headers["Authorization"] = f"Bearer {os.getenv('EVAL_TOKEN')}"
    # Adjust this wrapper to whatever the endpoint documents.
    payload = {"team_id": os.getenv("TEAM_ID"), "results": results} if os.getenv("TEAM_ID") else results
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    print(f"\nSubmitted {len(results)} results -> HTTP {r.status_code}")
    print(r.text[:2000])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="inbox JSON file or path passed to loader.py")
    ap.add_argument("--loader-fn", help="name of the function in loader.py")
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "results.json"))
    ap.add_argument("--submit", action="store_true")
    args = ap.parse_args()

    records = load_records(args.source, args.loader_fn)
    reports = [process_email(r) for r in records]
    results = [to_submission(r) for r in reports]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=2)
    with open(args.out.replace(".json", "_full.json"), "w") as fh:
        json.dump(reports, fh, indent=2, default=str)

    review = sum(r["needs_human_review"] for r in reports)
    mism = sum(r["mismatch_found"] for r in reports)
    print(f"Processed {len(reports)} emails: {mism} with mismatches, {review} sent to human review")
    print(f"Wrote {args.out}")
    local_score(records, reports)
    if args.submit:
        submit(results)


if __name__ == "__main__":
    main()
