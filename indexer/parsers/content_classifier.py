"""Content type classification for ISO document text chunks.

Classifies text into one of the defined content types using heuristic
pattern matching: heading, definition, note, table, annex, figure_caption,
or body_text.
"""

from __future__ import annotations

import re

# Valid content types
CONTENT_TYPES = frozenset(
    ["heading", "definition", "note", "table", "annex", "figure_caption", "body_text"]
)

# --- Patterns ---

# Note patterns: "NOTE", "NOTE 1", "Note 1 to entry", etc.
_NOTE_PATTERN = re.compile(
    r"^\s*NOTE\s*(\d+)?(\s+to\s+entry)?[\s:\u2014\u2013\-]",
    re.IGNORECASE,
)

# Figure caption: "Figure 1", "Figure A.1 — Title", etc.
_FIGURE_PATTERN = re.compile(
    r"^\s*(Figure|Fig\.?)\s+[A-Z]?\.?\d+(\.\d+)*\s*[\u2014\u2013\-:\s]?",
    re.IGNORECASE,
)

# Table header: "Table 1", "Table A.2 — Title", etc.
_TABLE_HEADER_PATTERN = re.compile(
    r"^\s*Table\s+[A-Z]?\.?\d+(\.\d+)*\s*[\u2014\u2013\-:\s]?",
    re.IGNORECASE,
)

# Table-like content: lines with multiple pipe or tab separators
_TABLE_CONTENT_PATTERN = re.compile(r"(\|.*\|)|(\t[^\t]+\t)")

# Annex heading: "Annex A", "Annex B (informative)", etc.
_ANNEX_PATTERN = re.compile(
    r"^\s*Annex\s+[A-Z]\s*[\(\u2014\u2013\-:\s]?",
    re.IGNORECASE,
)

# ISO-style numbered clause headings: "4", "4.1", "4.1.2", "A.5.1"
_CLAUSE_HEADING_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)*|[A-Z]\.\d+(?:\.\d+)*)\s+\S",
)

# Definition patterns: "3.1\nterm\ndefinition" or "term: definition"
_DEFINITION_TERM_PATTERN = re.compile(
    r"^\s*\d+\.\d+(?:\.\d+)*\s*$",  # standalone clause number (term entry)
)
_DEFINITION_COLON_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z\s\-]{1,60}:\s+\S",  # "term: definition text"
)


def classify_content_type(text: str, clause_info: dict | None = None) -> str:
    """Classify a text chunk into a content type.

    Args:
        text: The text content to classify.
        clause_info: Optional dict with context such as 'clause_number',
            'is_annex', 'title', etc.

    Returns:
        One of: 'heading', 'definition', 'note', 'table', 'annex',
        'figure_caption', or 'body_text'.
    """
    if not text or not text.strip():
        return "body_text"

    stripped = text.strip()
    lines = stripped.split("\n")
    first_line = lines[0].strip()

    # --- Check clause_info first for annex context ---
    if clause_info:
        if clause_info.get("is_annex"):
            # If the text itself is an annex heading, classify as annex
            if _ANNEX_PATTERN.match(first_line):
                return "annex"
            # If clause_info says we're in an annex section and text is short
            # (likely a sub-heading within the annex), still classify by content
            # but check for annex heading pattern
        clause_number = clause_info.get("clause_number", "")
        if isinstance(clause_number, str) and clause_number.lower().startswith("annex"):
            if _ANNEX_PATTERN.match(first_line):
                return "annex"

    # --- Figure caption ---
    if _FIGURE_PATTERN.match(first_line):
        return "figure_caption"

    # --- Note ---
    if _NOTE_PATTERN.match(first_line):
        return "note"

    # --- Table ---
    if _TABLE_HEADER_PATTERN.match(first_line):
        return "table"
    # Check for table-like content (multiple separators across lines)
    table_line_count = sum(
        1 for line in lines if _TABLE_CONTENT_PATTERN.search(line)
    )
    if table_line_count >= 2 or (len(lines) <= 3 and table_line_count >= 1):
        return "table"

    # --- Annex heading ---
    if _ANNEX_PATTERN.match(first_line):
        return "annex"

    # --- Definition ---
    # Short text with definition-like structure
    if len(lines) <= 5:
        if _DEFINITION_TERM_PATTERN.match(first_line) and len(lines) >= 2:
            return "definition"
        if _DEFINITION_COLON_PATTERN.match(first_line):
            return "definition"

    # --- Heading ---
    # Short text that looks like a section heading
    if len(lines) == 1 and len(first_line) < 120:
        # Numbered clause heading pattern
        if _CLAUSE_HEADING_PATTERN.match(first_line):
            return "heading"
        # All-caps short lines (common for ISO headings)
        if first_line.isupper() and len(first_line) < 80:
            return "heading"

    # --- Default: body_text ---
    return "body_text"
