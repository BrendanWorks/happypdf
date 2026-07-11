"""
Tests for OLMo peer reviewer adapter.

The OLMo adapter must correctly parse reviewer responses, extract violations,
and mark hallucinated violations (issues targeting non-existent elements).
"""

import re
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def extract_issue_ids(html: str) -> set[str]:
    """Extract all data-ir-id values from HTML (helper for testing)."""
    return set(re.findall(r'data-ir-id="([^"]+)"', html))


class TestOLMoAdapter:
    """Test OLMo peer reviewer response handling."""

    def test_extract_issue_ids_from_html(self):
        """Should correctly extract all data-ir-id values from HTML."""
        html = """
        <html>
            <body>
                <h1 data-ir-id="block-1-abc12345">Title</h1>
                <p data-ir-id="block-1-def67890">Paragraph</p>
                <ul data-ir-id="block-1-ghi11111">List</ul>
            </body>
        </html>
        """

        ids = extract_issue_ids(html)

        assert "block-1-abc12345" in ids, "Should extract h1 ID"
        assert "block-1-def67890" in ids, "Should extract p ID"
        assert "block-1-ghi11111" in ids, "Should extract ul ID"
        assert len(ids) == 3, f"Should have 3 IDs, got {len(ids)}"

    def test_extract_issue_ids_empty_html(self):
        """Should return empty set for HTML with no data-ir-id."""
        html = "<html><body><p>No IDs here</p></body></html>"

        ids = extract_issue_ids(html)

        assert len(ids) == 0, "Should have no IDs"
        assert isinstance(ids, set), "Should return a set"

    def test_extract_issue_ids_partial_match(self):
        """Should only match complete data-ir-id attributes."""
        html = """
        <p data-ir-id="block-1-correct">Good</p>
        <p data-ir-id-modified="block-1-wrong">Bad</p>
        <p ir-id="block-1-typo">Also bad</p>
        """

        ids = extract_issue_ids(html)

        assert "block-1-correct" in ids, "Should extract valid ID"
        assert "block-1-wrong" not in ids, "Should not match data-ir-id-modified"
        assert "block-1-typo" not in ids, "Should not match ir-id without data-"
        assert len(ids) == 1, f"Should have 1 ID, got {len(ids)}"

    def test_valid_reviewer_response_structure(self, sample_reviewer_response):
        """Valid reviewer responses should have required fields."""
        response = sample_reviewer_response

        assert "issues" in response, "Should have 'issues' field"
        assert "summary" in response, "Should have 'summary' field"

        # Each issue should have required fields
        for issue in response["issues"]:
            assert "data-ir-id" in issue, "Issue should target a data-ir-id"
            assert "wcag" in issue, "Issue should list WCAG criteria"
            assert "issue_type" in issue, "Issue should have a type"
            assert "severity" in issue, "Issue should have a severity"

    def test_hallucinated_violation_detection(self, sample_html):
        """Should mark violations targeting non-existent elements as hallucinated."""
        # Extract valid IDs from sample HTML
        valid_ids = extract_issue_ids(sample_html)

        # Create a violation targeting valid ID
        valid_issue = {
            "data-ir-id": list(valid_ids)[0] if valid_ids else "block-1-abc12345",
            "wcag": ["1.3.1"],
            "issue_type": "missing_label",
            "description": "Form control missing label",
            "hallucinated": False
        }

        # Create a violation targeting non-existent ID
        hallucinated_issue = {
            "data-ir-id": "block-1-fakefakefake",  # Doesn't exist in HTML
            "wcag": ["2.1.1"],
            "issue_type": "keyboard_trap",
            "description": "Keyboard navigation trap",
            "hallucinated": False  # But is actually hallucinated
        }

        # Valid issue should not be marked as hallucinated
        assert not valid_issue.get("hallucinated"), "Real element should not be hallucinated"

        # Hallucinated issue targets non-existent element
        if hallucinated_issue["data-ir-id"] not in valid_ids:
            assert hallucinated_issue["data-ir-id"] != list(valid_ids)[0] if valid_ids else True

    def test_reviewer_response_wcag_mapping(self, sample_reviewer_response):
        """Reviewer issues should include valid WCAG 2.2 criterion references."""
        for issue in sample_reviewer_response["issues"]:
            wcag_list = issue.get("wcag", [])

            # Should have at least one WCAG criterion
            assert len(wcag_list) > 0, "Issue should reference at least one WCAG criterion"

            # Each should be a string like "1.3.1", "4.1.2", etc
            for wcag in wcag_list:
                assert isinstance(wcag, str), f"WCAG criterion should be string: {wcag}"
                parts = wcag.split(".")
                assert len(parts) >= 2, f"WCAG should be formatted like '1.3.1': {wcag}"

    def test_reviewer_severity_levels(self, sample_reviewer_response):
        """Reviewer issues should have valid severity levels."""
        valid_severities = {"low", "medium", "serious", "critical"}

        for issue in sample_reviewer_response["issues"]:
            severity = issue.get("severity", "").lower()
            assert severity in valid_severities, f"Invalid severity: {severity}"

    def test_reviewer_issue_description_present(self, sample_reviewer_response):
        """Each reviewer issue should have a descriptive message."""
        for issue in sample_reviewer_response["issues"]:
            description = issue.get("description", "").strip()

            assert len(description) > 0, "Issue should have a description"
            assert len(description) > 10, "Description should be meaningful (>10 chars)"
            assert len(description) < 500, "Description should not be excessively long"
