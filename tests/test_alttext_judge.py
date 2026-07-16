"""
Tests for the alt-text judge (PointCheck Phase 2) — the GPU-free parts.

Covers:
  - parse_judge_response: the model's free-text output is parsed robustly
    (labeled format, loose "4/5" phrasing, garbage -> None, never a fabricated
    score).
  - judge_alt_text_map: batch assembly, summary shape, and the empty cases,
    with the Modal call mocked (no GPU, no network).

The Modal function itself (modal/modal_alttext_judge.py::judge_alt_text) is
validated on staging via `modal run` smoke tests — see
docs/POINTCHECK_INTEGRATION.md Phase 2 verification.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "modal"))
sys.path.insert(0, str(ROOT / "src"))

import build_syllabus_slice as bss  # noqa: E402
from modal_alttext_judge import build_judge_prompt, parse_judge_response  # noqa: E402

# ---------------------------------------------------------------------------
# parse_judge_response
# ---------------------------------------------------------------------------


def test_parse_well_formed():
    out = parse_judge_response(
        "SCORE: 4\nCRITIQUE: Accurate but omits the axis labels.\nLONG_DESC: yes"
    )
    assert out["score"] == 4
    assert out["critique"] == "Accurate but omits the axis labels."
    assert out["long_desc_opinion"] is True


def test_parse_loose_score_phrasing():
    out = parse_judge_response("I would rate this alt text 2/5. It is too vague.")
    assert out["score"] == 2
    assert out["long_desc_opinion"] is None  # not stated -> unavailable, not False


def test_parse_garbage_never_fabricates():
    out = parse_judge_response("The image shows a cat sitting on a windowsill.")
    assert out["score"] is None
    assert out["critique"]  # raw text preserved as the critique
    assert out["long_desc_opinion"] is None


def test_parse_empty():
    out = parse_judge_response("")
    assert out == {"score": None, "critique": "", "long_desc_opinion": None}


def test_parse_no_answer_for_long_desc_variants():
    assert parse_judge_response("SCORE: 5\nLONG_DESC: no")["long_desc_opinion"] is False
    assert parse_judge_response("SCORE: 5\nLONG_DESC: NO")["long_desc_opinion"] is False
    assert parse_judge_response("score = 3")["score"] == 3


def test_parse_critique_is_bounded():
    out = parse_judge_response("CRITIQUE: " + "very " * 200 + "long")
    assert len(out["critique"]) <= 300


def test_prompt_includes_alt_and_context():
    p = build_judge_prompt("A bar chart of quarterly revenue", "Q3 results section")
    assert "A bar chart of quarterly revenue" in p
    assert "Q3 results section" in p
    assert "SCORE" in p and "LONG_DESC" in p


# ---------------------------------------------------------------------------
# judge_alt_text_map (Modal call mocked)
# ---------------------------------------------------------------------------


class _FakeFn:
    def __init__(self, results):
        self._results = results
        self.called_with = None

    def remote(self, items):
        self.called_with = items
        return self._results


def _patch_modal(monkeypatch, fake_fn):
    monkeypatch.setattr(
        bss.modal.Function, "from_name", staticmethod(lambda app, fn: fake_fn)
    )


def test_judge_map_summary(monkeypatch):
    images = [
        {"filename": "img1.png", "b64": "aGk=", "context": "revenue section"},
        {"filename": "img2.png", "b64": "aGk=", "context": ""},
    ]
    alt_map = {
        "img1.png": {"alt_text": "A bar chart of quarterly revenue"},
        "img2.png": {"alt_text": "img2.png"},  # filename alt — judge should hate it
    }
    fake = _FakeFn(
        [
            {"filename": "img1.png", "success": True, "score": 5,
             "critique": "Accurate.", "long_desc_opinion": True},
            {"filename": "img2.png", "success": True, "score": 1,
             "critique": "Alt text is just a filename.", "long_desc_opinion": False},
        ]
    )
    _patch_modal(monkeypatch, fake)

    out = bss.judge_alt_text_map(images, alt_map)
    assert out["images_judged"] == 2
    assert out["avg_score"] == 3.0
    assert out["flagged_low_quality"] == ["img2.png"]
    # Batch call carried both images with their alt text and context
    assert [i["filename"] for i in fake.called_with] == ["img1.png", "img2.png"]
    assert fake.called_with[0]["alt_text"] == "A bar chart of quarterly revenue"


def test_judge_map_strict_but_acceptable_score_not_flagged(monkeypatch):
    # The judge is strict — 3 means "acceptable but improvable" per the
    # calibration run, and must NOT be flagged (threshold is <=2).
    images = [{"filename": "img1.png", "b64": "aGk=", "context": ""}]
    alt_map = {"img1.png": {"alt_text": "A university logo"}}
    fake = _FakeFn(
        [{"filename": "img1.png", "success": True, "score": 3,
          "critique": "Lacks detail.", "long_desc_opinion": False}]
    )
    _patch_modal(monkeypatch, fake)
    assert bss.judge_alt_text_map(images, alt_map)["flagged_low_quality"] == []


def test_judge_map_skips_images_without_alt(monkeypatch):
    images = [{"filename": "img1.png", "b64": "aGk=", "context": ""}]
    _patch_modal(monkeypatch, _FakeFn([]))
    assert bss.judge_alt_text_map(images, {"img1.png": {"alt_text": ""}}) is None


def test_judge_map_empty_images(monkeypatch):
    _patch_modal(monkeypatch, _FakeFn([]))
    assert bss.judge_alt_text_map([], {}) is None


def test_judge_map_failed_items_not_flagged(monkeypatch):
    images = [{"filename": "img1.png", "b64": "aGk=", "context": ""}]
    alt_map = {"img1.png": {"alt_text": "Some alt"}}
    fake = _FakeFn(
        [{"filename": "img1.png", "success": False, "score": None,
          "critique": "", "long_desc_opinion": None}]
    )
    _patch_modal(monkeypatch, fake)
    out = bss.judge_alt_text_map(images, alt_map)
    assert out["flagged_low_quality"] == []
    assert out["avg_score"] is None
