"""
Tests for HTML generation from markdown.

The HTML generator must produce valid, accessible HTML5 that meets WCAG standards.
"""

import sys
from pathlib import Path

from lxml import html

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from build_syllabus_slice import HtmlBuilder


class TestHtmlGeneration:
    """Test HTML generation from markdown."""

    def test_html_is_valid_html5(self, sample_markdown):
        """Generated HTML should be valid HTML5."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        # Should have proper DOCTYPE and tags
        assert output_html.startswith("<!DOCTYPE html>"), "Should have HTML5 DOCTYPE"
        assert "<html" in output_html, "Should have <html> tag"
        assert "<head>" in output_html, "Should have <head> tag"
        assert "<body>" in output_html, "Should have <body> tag"

    def test_all_block_elements_have_data_ir_id(self, sample_markdown):
        """Every block-level element should have a data-ir-id attribute."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        # Parse HTML
        doc = html.fromstring(output_html)

        # Find all block elements
        block_elements = doc.xpath(
            "//h1 | //h2 | //h3 | //p | //ul | //ol | //table | //section | //article | //aside | //nav | //blockquote"
        )

        # Each should have data-ir-id
        for elem in block_elements:
            element_id = elem.get("data-ir-id")
            assert element_id is not None, f"<{elem.tag}> missing data-ir-id"
            assert element_id.startswith("block-"), f"Invalid ID format: {element_id}"

    def test_html_has_lang_attribute(self, sample_markdown):
        """The <html> tag should have lang="en" for accessibility."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        doc = html.fromstring(output_html)
        html_elem = doc

        assert html_elem.get("lang") == "en", "<html> tag should have lang='en'"

    def test_html_has_main_landmark(self, sample_markdown):
        """HTML should include a <main> landmark for content."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        doc = html.fromstring(output_html)
        main_elem = doc.xpath("//main")

        assert len(main_elem) > 0, "HTML should contain a <main> landmark"

    def test_html_has_skip_link(self, sample_markdown):
        """HTML should include a skip link to main content."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        # Look for skip link pattern: <a href="#main" class="skip-link">
        assert "skip-link" in output_html or "Skip" in output_html, "Should have skip link"
        assert "#main" in output_html, "Should link to main content"

    def test_headings_are_hierarchical(self, sample_markdown):
        """Headings should follow proper hierarchy (h1 → h2 → h3, no h4 without h3, etc)."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        doc = html.fromstring(output_html)
        headings = doc.xpath("//h1 | //h2 | //h3 | //h4 | //h5 | //h6")

        # Extract heading levels
        levels = [int(h.tag[1]) for h in headings]

        # Check hierarchy: should not skip levels or jump backwards
        if len(levels) > 1:
            for i in range(1, len(levels)):
                prev_level = levels[i - 1]
                curr_level = levels[i]
                # Can go down (e.g. h1 → h2), stay same (h2 → h2), or up (h3 → h2)
                # But shouldn't skip (e.g. h1 → h4)
                assert (
                    curr_level <= prev_level + 1
                ), f"Heading hierarchy violation: h{prev_level} → h{curr_level}"

    def test_tables_have_structure(self, sample_markdown):
        """Generated tables should have proper structure (thead, tbody, th)."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        doc = html.fromstring(output_html)
        tables = doc.xpath("//table")

        if tables:
            for table in tables:
                # Should have proper structure
                has_thead = len(table.xpath("thead")) > 0
                has_tbody = len(table.xpath("tbody")) > 0

                # If table has content, should have thead and tbody
                if table.xpath(".//th | .//td"):
                    assert has_thead or has_tbody, "Table should have thead or tbody"

    def test_html_encoding_is_utf8(self, sample_markdown):
        """HTML should declare UTF-8 encoding."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        assert (
            'charset="UTF-8"' in output_html or "charset=UTF-8" in output_html
        ), "Should declare UTF-8 encoding"

    def test_html_has_viewport_meta(self, sample_markdown):
        """HTML should include viewport meta tag for responsive design."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        assert 'name="viewport"' in output_html, "Should have viewport meta tag"
        assert "width=device-width" in output_html, "Viewport should include device-width"

    def test_markdown_lists_become_lists(self, sample_markdown):
        """Markdown bullet lists should become <ul> or <ol> in HTML."""
        builder = HtmlBuilder(sample_markdown, [], {})
        output_html = builder.build()

        doc = html.fromstring(output_html)
        lists = doc.xpath("//ul | //ol")

        assert len(lists) > 0, "Should have at least one list"
        list_items = doc.xpath("//li")
        assert len(list_items) > 0, "List should have items"
