"""ISO clause and standard detection from document text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DetectedClause:
    clause_number: str
    title: str | None
    level: int
    page_number: int | None
    line_text: str


# ISO-style clause headings: 4, 4.1, 4.1.1, Annex A, A.5.1, Figure 1, etc.
CLAUSE_PATTERNS = [
    re.compile(
        r"^(Annex\s+[A-Z])\s*[\u2014\u2013\-:]?\s*(.+)?$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^([A-Z]\.\d+(?:\.\d+)*)\s+(.+)$",
        re.MULTILINE,
    ),
    re.compile(
        r"^(\d+(?:\.\d+)*)\s+(.+)$",
        re.MULTILINE,
    ),
]

FIGURE_PATTERN = re.compile(
    r"^(Figure|Fig\.?)\s+(\d+(?:\.\d+)*)[\s\u2014\u2013\-:]*(.+)?$",
    re.IGNORECASE,
)

STANDARD_ID_PATTERNS = [
    re.compile(r"\b(ISO[\s_-]*/?[\s_-]*IEC[\s_-]*\d{4,5}(?:-\d+)?(?::\d{4})?)(?![A-Za-z0-9])", re.IGNORECASE),
    re.compile(r"\b(ISO[\s_-]*\d{4,5}(?:-\d+)?(?::\d{4})?)(?![A-Za-z0-9])", re.IGNORECASE),
    re.compile(r"\b(IEC[\s_-]*\d{4,5}(?:-\d+)?(?::\d{4})?)(?![A-Za-z0-9])", re.IGNORECASE),
]


def normalize_standard_id(raw: str) -> str:
    cleaned = re.sub(r"[\s_]+", " ", raw.strip())
    cleaned = cleaned.replace(" / ", "/").replace("/ ", "/").replace(" /", "/")
    return cleaned.upper()


def detect_standard_id(text: str, filename: str) -> str | None:
    for source in (filename, text[:5000]):
        for pattern in STANDARD_ID_PATTERNS:
            match = pattern.search(source)
            if match:
                return normalize_standard_id(match.group(1))
    return None


def clause_level(clause_number: str) -> int:
    if clause_number.lower().startswith("annex"):
        return 1
    if re.match(r"^[A-Z]\.", clause_number):
        return clause_number.count(".") + 1
    return clause_number.count(".") + 1


def parent_clause_number(clause_number: str) -> str | None:
    if clause_number.lower().startswith("annex"):
        return None
    if "." in clause_number:
        return clause_number.rsplit(".", 1)[0]
    return None


def detect_clause_from_line(line: str, page_number: int | None = None) -> DetectedClause | None:
    stripped = line.strip()
    if not stripped or len(stripped) > 300:
        return None

    fig_match = FIGURE_PATTERN.match(stripped)
    if fig_match:
        num = fig_match.group(2)
        caption = (fig_match.group(3) or "").strip() or None
        return DetectedClause(
            clause_number=f"Figure {num}",
            title=caption,
            level=99,
            page_number=page_number,
            line_text=stripped,
        )

    for pattern in CLAUSE_PATTERNS:
        match = pattern.match(stripped)
        if not match:
            continue
        clause_number = match.group(1).strip()
        title = (match.group(2) or "").strip() if match.lastindex and match.lastindex >= 2 else None
        if title and len(title) < 2:
            title = None
        # Skip lines that look like page numbers or dates
        if re.match(r"^\d{4}$", clause_number):
            continue
        return DetectedClause(
            clause_number=clause_number,
            title=title,
            level=clause_level(clause_number),
            page_number=page_number,
            line_text=stripped,
        )
    return None


def split_text_by_clauses(
    pages: list[tuple[int, str]],
) -> list[tuple[DetectedClause | None, int, str]]:
    """Split document pages into clause-segmented blocks."""
    segments: list[tuple[DetectedClause | None, int, str]] = []
    current_clause: DetectedClause | None = None
    current_lines: list[str] = []
    current_page = pages[0][0] if pages else 1

    def flush() -> None:
        nonlocal current_lines
        if current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                segments.append((current_clause, current_page, text))
            current_lines = []

    for page_num, page_text in pages:
        for line in page_text.split("\n"):
            detected = detect_clause_from_line(line, page_num)
            if detected and detected.level < 99:
                flush()
                current_clause = detected
                current_page = page_num
                if detected.title:
                    current_lines.append(line)
                continue
            current_lines.append(line)

    flush()
    return segments


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))
