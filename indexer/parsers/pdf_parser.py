"""PDF document parser using PyMuPDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class ParsedPage:
    page_number: int
    text: str


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


def parse_pdf(file_path: Path) -> ParsedDocument:
    doc = fitz.open(str(file_path))
    result = ParsedDocument(file_path=file_path)
    metadata = doc.metadata or {}
    result.title = metadata.get("title") or file_path.stem

    for i, page in enumerate(doc):
        page_number = i + 1
        text = page.get_text("text")
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
