#!/usr/bin/env python3
"""
Deterministic patch applicator: apply a judge patch manifest to baseline HTML.

Pure Python + lxml. No LLM calls — the judge already vetted every patch.
All-or-nothing: if any patch fails, the whole batch is rolled back (nothing is
written) and a PatchError is raised. Applied patches are logged to
output/patches_applied.json.

Operations
----------
  annotate : set target_attribute = new_value on the element
  replace  : if target_attribute is given, set that attribute; otherwise replace
             the element's text content with new_value
  wrap     : wrap the element in `wrapper_tag` carrying optional wrapper_attributes
  insert   : insert the `new_element` HTML fragment as a sibling (`position`:
             "after" [default] or "before")

Run
---
  python src/applicator.py                          # uses output/patch_manifest.json
  python src/applicator.py --manifest tests/applicator_ops.json
"""

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

from lxml import etree, html

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HTML = ROOT / "output" / "syllabus_scored.html"
DEFAULT_MANIFEST = ROOT / "output" / "patch_manifest.json"
OUT_HTML = ROOT / "output" / "syllabus_patched.html"
OUT_LOG = ROOT / "output" / "patches_applied.json"


class PatchError(Exception):
    """Raised when a patch cannot be applied; triggers a full rollback."""


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def build_index(tree) -> dict[str, "etree._Element"]:
    """Map data-ir-id -> element node."""
    return {el.get("data-ir-id"): el for el in tree.xpath("//*[@data-ir-id]")}


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------
def _op_annotate(el, patch) -> str:
    attr = patch["target_attribute"]
    el.set(attr, patch["new_value"])
    return f'set {attr}="{patch["new_value"]}"'


def _op_replace(el, patch) -> str:
    attr = patch.get("target_attribute")
    if attr:
        el.set(attr, patch["new_value"])
        return f'replaced attribute {attr}="{patch["new_value"]}"'
    # Replace text content, preserving child elements' structure: drop existing
    # text but keep children (alt/text rewrites target leaf elements in practice).
    el.text = patch["new_value"]
    return f'replaced text content with "{patch["new_value"]}"'


def _op_wrap(el, patch) -> str:
    parent = el.getparent()
    if parent is None:
        raise PatchError("cannot wrap the root element")
    wrapper = parent.makeelement(patch["wrapper_tag"], dict(patch.get("wrapper_attributes", {})))
    idx = parent.index(el)
    # Preserve document text flow: the wrapper inherits the element's tail.
    wrapper.tail = el.tail
    el.tail = None
    parent.insert(idx, wrapper)
    wrapper.append(el)  # moves el out of parent and into wrapper
    return f"wrapped in <{patch['wrapper_tag']}>"


def _op_insert(el, patch) -> str:
    parent = el.getparent()
    if parent is None:
        raise PatchError("cannot insert a sibling of the root element")
    frag = html.fragment_fromstring(patch["new_element"])
    idx = parent.index(el)
    position = patch.get("position", "after")
    if position == "after":
        frag.tail = el.tail
        el.tail = None
        parent.insert(idx + 1, frag)
    elif position == "before":
        parent.insert(idx, frag)
    else:
        raise PatchError(f"invalid insert position: {position!r}")
    return f"inserted {position}: {patch['new_element']}"


OPERATIONS = {
    "annotate": _op_annotate,
    "replace": _op_replace,
    "wrap": _op_wrap,
    "insert": _op_insert,
}


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def apply_patches(baseline_html: str, manifest: list[dict]) -> tuple[str, list[dict]]:
    """Apply all patches or none. Returns (patched_html, applied_log).

    Raises PatchError (after logging) if any patch fails — the working tree is
    discarded and nothing is persisted by the caller.
    """
    tree = html.document_fromstring(baseline_html)
    pristine = copy.deepcopy(tree)  # instant rollback target
    index = build_index(tree)

    applied: list[dict] = []
    for i, patch in enumerate(manifest):
        eid = patch.get("element_id")
        op = patch.get("operation")
        entry = {"index": i, "element_id": eid, "operation": op,
                 "new_value": patch.get("new_value")}
        try:
            el = index.get(eid)
            if el is None:
                raise PatchError(f"no element with data-ir-id={eid!r}")
            if op not in OPERATIONS:
                raise PatchError(f"unknown operation {op!r}")
            detail = OPERATIONS[op](el, patch)
            # wrap/insert mutate structure but never remove data-ir-id; refresh
            # the index so later patches on new/moved nodes resolve correctly.
            index = build_index(tree)
            entry.update(status="applied", detail=detail)
            applied.append(entry)
            log(f"  ✓ [{eid}] {op}: {detail}")
        except PatchError as e:
            entry.update(status="failed", error=str(e))
            applied.append(entry)
            log(f"  ✗ [{eid}] {op}: {e} — ROLLING BACK all {len(applied) - 1} applied patch(es)")
            _ = pristine  # discarded; nothing written
            _write_log(applied, rolled_back=True)
            raise PatchError(f"patch {i} failed ({e}); rolled back") from e

    # Preserve the leading audit comment + doctype that lxml drops on output.
    prefix = baseline_html[: baseline_html.lower().find("<!doctype")] if "<!doctype" in baseline_html.lower() else ""
    body = html.tostring(tree, encoding="unicode", doctype="<!DOCTYPE html>")
    patched_html = prefix + body
    _write_log(applied, rolled_back=False)
    return patched_html, applied


def _write_log(applied: list[dict], rolled_back: bool) -> None:
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.write_text(json.dumps(
        {"rolled_back": rolled_back,
         "applied": [a for a in applied if a["status"] == "applied"],
         "failed": [a for a in applied if a["status"] == "failed"]},
        indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply a patch manifest to baseline HTML.")
    ap.add_argument("--html", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--out", type=Path, default=OUT_HTML)
    args = ap.parse_args()

    log("=" * 70)
    log(f"Applicator starting  html={args.html.name}  manifest={args.manifest.name}")
    if not args.html.exists() or not args.manifest.exists():
        log("FATAL: missing input HTML or manifest")
        return 1

    baseline = args.html.read_text()
    manifest = json.loads(args.manifest.read_text())
    log(f"applying {len(manifest)} patch(es)...")
    try:
        patched, applied = apply_patches(baseline, manifest)
    except PatchError as e:
        log("=" * 70)
        log(f"ABORTED: {e}  (no output written; see {OUT_LOG})")
        return 2

    args.out.write_text(patched)
    log("=" * 70)
    log(f"DONE  applied={len(applied)}  out={args.out}  log={OUT_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
