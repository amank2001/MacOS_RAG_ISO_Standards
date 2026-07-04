"""DOCX document parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass
class ParsedPage:
    page_number: int
    text: str


@dataclass
class ParsedDocument:
    file_path: Path
    file_type: str = "docx"
    title: str | None = None
    pages: list[ParsedPage] = field(default_factory=list)
    images: list = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


def _iter_block_items(parent):
    from docx.document import Document as DocxDoc

    if isinstance(parent, DocxDoc):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._element
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def parse_docx(file_path: Path) -> ParsedDocument:
    doc = DocxDocument(str(file_path))
    result = ParsedDocument(file_path=file_path)
    result.title = doc.core_properties.title or file_path.stem

    lines: list[str] = []
    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                lines.append(text)
        elif isinstance(block, Table):
            for row in block.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))

    # DOCX has no native pages; treat as single logical page stream
    result.pages.append(ParsedPage(page_number=1, text="\n".join(lines)))
    return result
