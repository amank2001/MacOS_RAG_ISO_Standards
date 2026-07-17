"""PDF document parser using PyMuPDF."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class TextBlock:
    page_number: int
    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    block_index: int


@dataclass
class ParsedPage:
    page_number: int
    text: str
    blocks: list[TextBlock] = field(default_factory=list)


@dataclass
class ParsedImage:
    page_number: int
    image_index: int
    data: bytes
    ext: str
    width: int
    height: int


@dataclass
class ParsedDocument:
    file_path: Path
    file_type: str = "pdf"
    title: str | None = None
    pages: list[ParsedPage] = field(default_factory=list)
    images: list[ParsedImage] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


def _extract_blocks(page, page_number: int) -> list[TextBlock]:
    """Extract text blocks with bbox from a page using get_text("dict").

    Returns a list of TextBlock objects with bounding box coordinates.
    Returns an empty list if no text blocks can be extracted.
    """
    try:
        page_dict = page.get_text("dict")
    except Exception:
        return []

    blocks: list[TextBlock] = []
    raw_blocks = page_dict.get("blocks", [])

    for block_index, block in enumerate(raw_blocks):
        # Only process text blocks (type 0); skip image blocks (type 1)
        if block.get("type", 0) != 0:
            continue

        # Assemble text from lines -> spans
        lines = block.get("lines", [])
        text_parts: list[str] = []
        for line in lines:
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans)
            text_parts.append(line_text)

        text = "\n".join(text_parts).strip()
        if not text:
            continue

        bbox = block.get("bbox", (0.0, 0.0, 0.0, 0.0))
        blocks.append(
            TextBlock(
                page_number=page_number,
                text=text,
                bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                block_index=block_index,
            )
        )

    return blocks


def parse_pdf(file_path: Path) -> ParsedDocument:
    doc = fitz.open(str(file_path))
    result = ParsedDocument(file_path=file_path)
    metadata = doc.metadata or {}
    result.title = metadata.get("title") or file_path.stem

    for i, page in enumerate(doc):
        page_number = i + 1

        # Try structured extraction with bbox coordinates
        blocks = _extract_blocks(page, page_number)

        if blocks:
            # Assemble page text from extracted blocks
            text = "\n\n".join(block.text for block in blocks)
            result.pages.append(
                ParsedPage(page_number=page_number, text=text, blocks=blocks)
            )
        else:
            # Fall back to plain text extraction (no bbox data)
            text = page.get_text("text").strip()
            if text:
                logger.warning(
                    "Page %d of %s: get_text('dict') returned no blocks, "
                    "falling back to plain text extraction (scanned page?)",
                    page_number,
                    file_path.name,
                )
            result.pages.append(ParsedPage(page_number=page_number, text=text))

        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                base = doc.extract_image(xref)
                if base and base.get("width", 0) >= 80 and base.get("height", 0) >= 80:
                    result.images.append(
                        ParsedImage(
                            page_number=page_number,
                            image_index=img_index,
                            data=base["image"],
                            ext=base.get("ext", "png"),
                            width=base["width"],
                            height=base["height"],
                        )
                    )
            except Exception:
                continue

    doc.close()
    return result
