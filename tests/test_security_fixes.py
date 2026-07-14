"""
Tests for the July 2026 security-hardening pass.

Covers:
  - HTML injection defenses in the output builder (table sanitization,
    markdown-image escaping, entity-unescape path)
  - Report generator escaping of attacker-influenced manifest fields
  - BYOK plumbing that must never touch os.environ
  - Reviewer payload hygiene (data-URI stripping)
  - Persistent daily rate limiter
  - Preservation-gate fixes (pre-existing heading skips, empty original)
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import gate  # noqa: E402
import judge  # noqa: E402
import reviewers  # noqa: E402
from build_syllabus_slice import HtmlBuilder  # noqa: E402
from job_store import DailyRateLimiter  # noqa: E402
from report_generator import generate_html_report  # noqa: E402

# ── Output HTML injection defenses ──────────────────────────────────────────


class TestTableSanitization:
    def test_script_tag_neutralized(self):
        """PDF text containing <script> must never become live markup."""
        tbl = "<table><tr><td>&lt;script&gt;alert(1)&lt;/script&gt;</td></tr></table>"
        out = HtmlBuilder._fix_table_html(tbl)
        assert "<script" not in out.lower()
        assert "<table" in out  # table structure survives

    def test_event_handler_attributes_stripped(self):
        tbl = '<table><tr><td onclick="alert(1)" style="x">cell</td></tr></table>'
        out = HtmlBuilder._fix_table_html(tbl)
        assert "onclick" not in out
        assert "style" not in out
        assert "cell" in out

    def test_structural_attributes_kept(self):
        tbl = '<table><tr><th scope="col" colspan="2">Head</th></tr></table>'
        out = HtmlBuilder._fix_table_html(tbl)
        assert 'scope="col"' in out
        assert 'colspan="2"' in out

    def test_entity_encoded_cells_recovered(self):
        """The original purpose still works: entity-encoded tags become real tags."""
        tbl = "<table>&lt;tr&gt;&lt;td&gt;data&lt;/td&gt;&lt;/tr&gt;</table>"
        out = HtmlBuilder._fix_table_html(tbl)
        assert "<td>" in out and "data" in out


class TestMarkdownImageEscaping:
    def test_attribute_injection_blocked(self):
        """![a](x" onerror=...) must not inject a live attribute."""
        from lxml import html as lxml_html

        out = HtmlBuilder._convert_markdown_images('![a](x.png" onerror="alert(1))')
        img = lxml_html.fragment_fromstring(out, create_parent="div").find(".//img")
        assert img is not None
        assert "onerror" not in img.attrib  # the quote was escaped, not parsed

    def test_alt_quotes_not_double_escaped(self):
        out = HtmlBuilder._convert_markdown_images('![say "hi"](x.png)')
        assert "&quot;" in out
        assert "&amp;quot;" not in out  # the old escape-order bug

    def test_javascript_src_dropped(self):
        out = HtmlBuilder._convert_markdown_images("![evil](javascript:alert(1))")
        assert "<img" not in out
        assert "evil" in out  # alt kept as visible text

    def test_surrounding_text_escaped(self):
        out = HtmlBuilder._convert_markdown_images("before <b>bold</b> ![a](x.png) after")
        assert "<b>" not in out
        assert "&lt;b&gt;" in out
        assert '<img src="x.png"' in out

    def test_plain_text_fully_escaped(self):
        out = HtmlBuilder._convert_markdown_images("<script>alert(1)</script>")
        assert "<script" not in out


class TestReportEscaping:
    def test_filename_script_escaped(self):
        manifest = {"name": '<script>alert("xss")</script>.pdf', "baseline": {}, "final": {}}
        html = generate_html_report(manifest)
        assert "<script>alert" not in html

    def test_enhancement_value_escaped(self):
        manifest = {
            "name": "doc.pdf",
            "baseline": {},
            "final": {},
            "enhancements": [
                {
                    "element_id": "block-1-abc",
                    "attribute": "aria-label",
                    "value": '"><img src=x onerror=alert(1)>',
                }
            ],
        }
        html = generate_html_report(manifest)
        assert "<img src=x" not in html  # never live markup
        assert "&lt;img src=x" in html  # rendered as inert escaped text


# ── BYOK plumbing ───────────────────────────────────────────────────────────


class TestByokPlumbing:
    def test_select_provider_prefers_byok_anthropic(self, monkeypatch):
        monkeypatch.delenv("HAPPYPDF_ALT_TEXT_PROVIDER", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert judge.select_provider({"anthropic": "sk-test"}) == "claude"
        assert judge.select_provider({"anthropic": None}) == "openai"

    def test_select_provider_env_fallback(self, monkeypatch):
        monkeypatch.delenv("HAPPYPDF_ALT_TEXT_PROVIDER", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
        assert judge.select_provider(None) == "claude"

    def test_make_live_provider_does_not_touch_environ(self, monkeypatch):
        """Building a BYOK provider must not write keys into the process env."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("REVIEWER_PROFILE", raising=False)
        import os

        before = dict(os.environ)
        reviewers.make_live_provider("olmo-only", openai_api_key="sk-byok-secret")
        assert dict(os.environ) == before
        assert "sk-byok-secret" not in str(os.environ)

    def test_gpt_available_with_byok_key_only(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert reviewers._available("gpt", openai_api_key="sk-byok") is True
        assert reviewers._available("gpt") is False


class TestDataUriHandling:
    def test_strip_data_uris_preserves_structure(self):
        html = (
            '<img data-ir-id="block-1-img" src="data:image/png;base64,'
            + "A" * 100000
            + '" alt="a chart">'
        )
        out = reviewers._strip_data_uris(html)
        assert len(out) < 200
        assert 'data-ir-id="block-1-img"' in out
        assert 'alt="a chart"' in out

    def test_judge_data_uri_image_extraction(self):
        el = {"attrs": {"src": "data:image/png;base64,iVBORw0KGgo="}}
        got = judge._data_uri_image(el)
        assert got == ("image/png", "iVBORw0KGgo=")
        assert judge._data_uri_image({"attrs": {"src": "x.png"}}) is None
        # Oversized images are not attached (API limits)
        big = {"attrs": {"src": "data:image/png;base64," + "A" * (judge.MAX_IMAGE_B64_CHARS + 1)}}
        assert judge._data_uri_image(big) is None


# ── Rate limiter ────────────────────────────────────────────────────────────


class TestDailyRateLimiter:
    def test_enforces_limit(self):
        rl = DailyRateLimiter(on_modal=False)
        results = [rl.check_and_increment(3) for _ in range(5)]
        assert [a for a, _ in results] == [True, True, True, False, False]

    def test_thread_safe(self):
        rl = DailyRateLimiter(on_modal=False)
        allowed_count = []

        def worker():
            allowed, _ = rl.check_and_increment(50)
            if allowed:
                allowed_count.append(1)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(allowed_count) == 50  # never overshoots the limit

    def test_prunes_old_days(self):
        rl = DailyRateLimiter(on_modal=False)
        rl._mem["2020-01-01"] = 7
        rl.check_and_increment(10)
        assert "2020-01-01" not in rl._mem


# ── Gate fixes ──────────────────────────────────────────────────────────────


def _doc(body: str) -> str:
    return f"<!DOCTYPE html><html><body>{body}</body></html>"


class TestGateHeadingOrder:
    def test_preexisting_skip_does_not_fail(self):
        """A baseline h1->h3 skip must not block every remediation round."""
        html = _doc("<h1>A</h1><h3>B</h3><p>text here</p>")
        res = gate.run_gate(html, html)
        heading = next(c for c in res["checks"] if c["name"] == "heading_order")
        assert heading["passed"] is True
        assert heading["preexisting_skips"] == [{"from": 1, "to": 3}]

    def test_new_skip_fails(self):
        orig = _doc("<h1>A</h1><h2>B</h2><p>text here</p>")
        patched = _doc("<h1>A</h1><h3>B</h3><p>text here</p>")
        res = gate.run_gate(orig, patched)
        heading = next(c for c in res["checks"] if c["name"] == "heading_order")
        assert heading["passed"] is False
        assert heading["new_skips"] == [{"from": 1, "to": 3}]

    def test_empty_original_text_passes(self):
        res = gate.run_gate(_doc(""), _doc(""))
        text = next(c for c in res["checks"] if c["name"] == "text_coverage")
        assert text["passed"] is True
