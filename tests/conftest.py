"""
Shared pytest fixtures for happypdf tests.

These fixtures provide sample data (markdown, HTML, API responses) that
multiple tests reuse, avoiding duplication and keeping tests maintainable.
"""

import json
from pathlib import Path

import pytest


# ── Paths ──────────────────────────────────────────────────────────────────

@pytest.fixture
def repo_root() -> Path:
    """Path to the happypdf project root."""
    return Path(__file__).parent.parent


@pytest.fixture
def sample_pdf_path(repo_root) -> Path:
    """Path to a sample PDF for testing."""
    return repo_root / "benchmark" / "syllabus_NOTaccessible.pdf"


# ── Sample Data ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_markdown() -> str:
    """Sample markdown output from olmOCR extraction."""
    return """# Course Syllabus

## Learning Objectives

By the end of this course, you will:

- Understand the fundamentals of web accessibility
- Write semantically correct HTML5
- Test with axe-core and NVDA screen readers

## Course Schedule

| Week | Topic |
|------|-------|
| 1 | Introduction |
| 2 | Landmarks |

## Grading

Final grade breakdown:
1. Participation (20%)
2. Assignments (40%)
3. Project (40%)

This course meets all WCAG 2.2 AA standards.
"""


@pytest.fixture
def sample_html() -> str:
    """Sample valid HTML5 output from HTML generator."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Course Syllabus</title>
    <style>
        body { font-family: system-ui, sans-serif; line-height: 1.6; }
        main { max-width: 800px; margin: 0 auto; }
    </style>
</head>
<body>
    <a href="#main" class="skip-link">Skip to main content</a>

    <main id="main">
        <h1 data-ir-id="block-1-abc12345">Course Syllabus</h1>

        <section>
            <h2 data-ir-id="block-1-def67890">Learning Objectives</h2>
            <p data-ir-id="block-1-ghi11111">By the end of this course, you will:</p>
            <ul data-ir-id="block-1-jkl22222">
                <li>Understand the fundamentals of web accessibility</li>
                <li>Write semantically correct HTML5</li>
                <li>Test with axe-core and NVDA screen readers</li>
            </ul>
        </section>

        <section>
            <h2 data-ir-id="block-1-mno33333">Course Schedule</h2>
            <table data-ir-id="block-1-pqr44444">
                <thead>
                    <tr>
                        <th>Week</th>
                        <th>Topic</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>1</td>
                        <td>Introduction</td>
                    </tr>
                </tbody>
            </table>
        </section>
    </main>
</body>
</html>
"""


@pytest.fixture
def sample_axe_results() -> dict:
    """Sample axe-core results (no violations)."""
    return {
        "passes": [
            {
                "id": "color-contrast",
                "impact": "serious",
                "tags": ["wcag2aa", "wcag412"],
                "description": "Elements must have sufficient color contrast",
                "help": "Ensure the contrast between foreground and background colors...",
                "nodes": [
                    {"html": "<h1>Course Syllabus</h1>", "target": ["h1"]}
                ],
                "violations": []
            }
        ],
        "violations": [],
        "incomplete": [],
        "inapplicable": []
    }


@pytest.fixture
def sample_reviewer_response() -> dict:
    """Sample response from OLMo peer reviewer."""
    return {
        "issues": [
            {
                "data-ir-id": "block-1-abc12345",
                "wcag": ["1.3.1"],
                "issue_type": "missing_landmark",
                "description": "Main content should be wrapped in a <main> landmark",
                "severity": "serious",
                "hallucinated": False
            }
        ],
        "summary": "Found 1 accessibility issue"
    }


# ── Test data helpers ──────────────────────────────────────────────────────

@pytest.fixture
def element_ids() -> dict:
    """Sample element IDs in expected format."""
    return {
        "h1": "block-1-abc12345",
        "section": "block-1-def67890",
        "p": "block-1-ghi11111",
        "ul": "block-1-jkl22222",
        "table": "block-1-pqr44444",
    }
