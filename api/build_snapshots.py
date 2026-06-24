#!/usr/bin/env python3
"""
Turn the real live-benchmark run into demo snapshots the API replays.

Reads benchmark/<doc>_live_summary.json + the live baseline/final HTML and emits
api/snapshots/<doc>.json — a self-contained, honest payload: real baseline (0
violations / N passes), per-round passes + patch counts + gate results, the
actual ARIA enhancements added (diffed baseline -> final), and the final HTML.

No fabrication: every number comes from the recorded live run.

Run: python api/build_snapshots.py
"""

import json
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmark"
OUT = ROOT / "api" / "snapshots"

DOCS = [
    ("syllabus", "AccessComputing Syllabus", "Clean digital PDF"),
    ("irs_schedule_c", "IRS Schedule C", "Dense tax form"),
    ("navy_bulletin", "Navy Bulletin 1943", "OCR'd historical scan"),
]


def _attrs_by_id(doc_html: str) -> dict[str, dict]:
    doc = html.document_fromstring(doc_html)
    return {el.get("data-ir-id"): dict(el.attrib) for el in doc.xpath("//*[@data-ir-id]")}


def enhancements(baseline_html: str, final_html: str) -> list[dict]:
    """The real ARIA attributes the loop added (diff baseline -> final)."""
    before, after = _attrs_by_id(baseline_html), _attrs_by_id(final_html)
    aria_keys = ("aria-label", "role", "aria-describedby", "aria-labelledby")
    added = []
    for eid, attrs in after.items():
        was = before.get(eid, {})
        for k in aria_keys:
            if attrs.get(k) and attrs.get(k) != was.get(k):
                added.append({"element_id": eid, "attribute": k, "value": attrs[k]})
    return added


def round_summary(r: dict) -> dict:
    audit = r.get("judge_audit", [])
    def count(dec):
        return sum(1 for a in audit if a["decision"] == dec)
    return {
        "round": r["round"],
        "patches_applied": r["patches_applied"],
        "passes": r["passes"],
        "score": r["score"],
        "violations": r["violations"],
        "gate_passed": r["gate_passed"],
        "gate_checks": r.get("gate_checks", []),
        "accepted": count("ACCEPT"),
        "needs_human": count("NEEDS_HUMAN"),
        "hallucinations": count("REJECT_HALLUCINATED"),
        "seconds": r.get("seconds"),
        "reviewers": sorted({rev for a in audit for rev in a.get("reviewers", [])}),
    }


def build(name: str, label: str, doctype: str) -> dict:
    summary = json.loads((BENCH / f"{name}_live_summary.json").read_text())
    baseline_html = (BENCH / f"{name}_live_baseline.html").read_text()
    final_html = (BENCH / f"{name}_live_final.html").read_text()
    rounds = [round_summary(r) for r in summary["rounds"] if r.get("status") == "accepted"]
    return {
        "id": name,
        "label": label,
        "doctype": doctype,
        "source": "real live run (OLMo + Gemini + GPT reviewers, Claude judge)",
        "baseline": summary["baseline"],
        "rounds": rounds,
        "final": summary["final"],
        "stopped_reason": summary["stopped_reason"],
        "total_seconds": summary["total_seconds"],
        "enhancements": enhancements(baseline_html, final_html),
        "final_html": final_html,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for name, label, doctype in DOCS:
        snap = build(name, label, doctype)
        (OUT / f"{name}.json").write_text(json.dumps(snap, indent=2))
        index.append({"id": name, "label": label, "doctype": doctype,
                      "baseline_passes": snap["baseline"]["passes"],
                      "final_passes": snap["final"]["passes"],
                      "enhancements": len(snap["enhancements"]),
                      "rounds": len(snap["rounds"])})
        print(f"  {name}: {snap['baseline']['passes']}->{snap['final']['passes']} passes, "
              f"{len(snap['enhancements'])} ARIA enhancements, {len(snap['rounds'])} rounds")
    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    print(f"wrote {len(index)} snapshots + index to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
