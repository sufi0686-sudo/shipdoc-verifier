"""Central configuration: field definitions, aliases and tunable thresholds.

Every threshold can be overridden with an environment variable so you can
tune against the scoreboard without touching code.
"""
import os

# The 7 fields the brief asks us to compare, in display order.
FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]

FIELD_LABELS = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify Party",
    "port_of_loading": "Port of Loading",
    "port_of_discharge": "Port of Discharge",
    "container_count": "Container Count",
    "gross_weight_kg": "Gross Weight (kg)",
}

# Different senders label the same field differently. Add new variants here
# whenever the scoreboard shows an extraction miss.
FIELD_ALIASES = {
    "shipper": [
        "shipper", "shipper name", "shipper/exporter", "shipper / exporter",
        "exporter", "consignor", "shipper details",
    ],
    "consignee": [
        "consignee", "consignee name", "consigned to", "consignee details",
        "importer", "receiver",
    ],
    "notify_party": [
        "notify party", "notify parties", "also notify", "notify address",
        "notify", "notify party details",
    ],
    "port_of_loading": [
        "port of loading", "port of load", "loading port", "pol",
        "port of shipment", "load port",
    ],
    "port_of_discharge": [
        "port of discharge", "discharge port", "pod", "port of destination",
        "destination port", "port of unloading",
    ],
    "container_count": [
        "container count", "no. of containers", "no of containers",
        "number of containers", "qty of containers", "container qty",
        "container quantity", "total containers", "containers", "cntr count",
        "no. of cntrs", "total no. of containers",
    ],
    "gross_weight_kg": [
        "gross weight", "gross wt", "gross wt.", "total gross weight", "g.w.",
        "g/w", "gw", "total weight", "cargo gross weight",
    ],
}

CATEGORIES = ["doc_comparison", "si_request", "invoice", "general_update", "spam"]


def _f(name, default):
    return float(os.getenv(name, default))


# Below this classifier confidence, the email is escalated to a human
# (and sent to the optional LLM for a second opinion first).
CLASSIFY_CONFIDENCE_THRESHOLD = _f("CLASSIFY_CONFIDENCE_THRESHOLD", "0.5")

# Party names (shipper/consignee/notify) are compared after normalisation.
# Exact normalised match = match. Similarity >= this = "uncertain" -> human.
PARTY_UNCERTAIN_THRESHOLD = _f("PARTY_UNCERTAIN_THRESHOLD", "0.85")

# Weights within this many kg are treated as equal (absorbs lbs->kg rounding).
WEIGHT_TOLERANCE_KG = _f("WEIGHT_TOLERANCE_KG", "1.0")

# Uncertain field comparisons are flagged as mismatches (safer before BL
# finalisation) and also escalated. Set to "false" to only escalate them.
UNCERTAIN_COUNTS_AS_MISMATCH = os.getenv("UNCERTAIN_COUNTS_AS_MISMATCH", "true").lower() == "true"

# Shape of `mismatched_fields` in the submission JSON:
#   dict   -> {"container_count": "SI: 3 / BL: 4"}
#   list   -> ["container_count"]
#   string -> "Container Count (SI: 3 / BL: 4); Gross Weight (kg) (...)"
# Check the scoreboard feedback and switch if needed.
MISMATCH_FORMAT = os.getenv("MISMATCH_FORMAT", "dict")

# Adds needs_human_review to the submission JSON when true.
INCLUDE_REVIEW_FLAG = os.getenv("INCLUDE_REVIEW_FLAG", "true").lower() == "true"

# Optional LLM second opinion (hybrid mode). Leave unset to run fully offline.
LLM_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_TIMEOUT_S = _f("LLM_TIMEOUT_S", "20")
