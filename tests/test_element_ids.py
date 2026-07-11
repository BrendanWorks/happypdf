"""
Tests for deterministic element ID generation.

Element IDs are critical for safe patching: they must be stable and unique
so that patches can target the correct elements without ambiguity.
"""

import sys
from pathlib import Path

import pytest

# Add src to path so we can import happypdf modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from build_syllabus_slice import HtmlBuilder


class TestElementIds:
    """Test element ID generation for deterministic patching."""

    def test_same_text_same_position_same_id(self):
        """Identical text at same position should always generate the same ID."""
        builder = HtmlBuilder("# Test", [], {})

        # Generate the same ID twice
        id1 = builder._id("Test Heading")
        id2 = builder._id("Test Heading")

        assert id1 == id2, "Same text should produce same ID"

    def test_different_text_different_id(self):
        """Different text should generate different IDs."""
        builder = HtmlBuilder("# Test", [], {})

        id1 = builder._id("First Heading")
        id2 = builder._id("Second Heading")

        assert id1 != id2, "Different text should produce different IDs"

    def test_element_id_format(self):
        """Element IDs should follow the format block-{page}-{hash}."""
        builder = HtmlBuilder("# Test", [], {})
        element_id = builder._id("Test Content")

        # Format: block-{page}-{8-char-hash}
        parts = element_id.split("-")
        assert len(parts) == 3, f"ID should have 3 parts: {element_id}"
        assert parts[0] == "block", f"First part should be 'block': {element_id}"
        assert parts[1] == "1", f"Second part (page) should be '1': {element_id}"
        assert len(parts[2]) == 8, f"Hash should be 8 chars, got {len(parts[2])}: {element_id}"

    def test_element_id_consistency_across_builders(self):
        """Element IDs should be consistent across different builder instances."""
        builder1 = HtmlBuilder("# Test", [], {})
        builder2 = HtmlBuilder("# Different", [], {})

        id1 = builder1._id("Consistent Text")
        id2 = builder2._id("Consistent Text")

        assert id1 == id2, "Different builders should generate same ID for same text"

    def test_element_id_case_sensitive(self):
        """Element IDs should be case-sensitive (different case = different ID)."""
        builder = HtmlBuilder("# Test", [], {})

        id_lower = builder._id("test content")
        id_upper = builder._id("Test Content")

        assert id_lower != id_upper, "Case should affect ID generation"

    def test_element_id_whitespace_normalized(self):
        """Element IDs should normalize whitespace for consistency."""
        builder = HtmlBuilder("# Test", [], {})

        id_single = builder._id("test content")
        id_double = builder._id("test  content")  # double space

        # Whitespace should be normalized so these produce the same ID
        assert id_single == id_double, "Whitespace should be normalized for consistency"

    def test_element_id_is_hex(self):
        """Hash portion of element ID should be hexadecimal."""
        builder = HtmlBuilder("# Test", [], {})
        element_id = builder._id("Test Content")

        parts = element_id.split("-")
        hash_part = parts[2]

        # Should be valid hex
        try:
            int(hash_part, 16)
        except ValueError:
            pytest.fail(f"Hash portion '{hash_part}' is not valid hexadecimal")
