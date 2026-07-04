"""Extract and save figures from parsed documents."""

from __future__ import annotations

from pathlib import Path

from indexer.parsers.clause_detector import FIGURE_PATTERN
from indexer.parsers.pdf_parser import ParsedDocument


def save_figures(
    parsed: ParsedDocument,
    output_dir: Path,
    document_id: int,
) -> list[dict]:
    """Save extracted images and return figure metadata dicts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    figures: list[dict] = []

    for img in parsed.images:
        filename = f"doc{document_id}_p{img.page_number}_i{img.image_index}.{img.ext}"
        image_path = output_dir / filename
        image_path.write_bytes(img.data)
        figures.append(
            {
                "page_number": img.page_number,
                "image_path": str(image_path),
                "width": img.width,
                "height": img.height,
                "figure_number": None,
                "caption": None,
            }
        )

    # Match figure captions from page text
    for page in parsed.pages:
        for line in page.text.split("\n"):
            match = FIGURE_PATTERN.match(line.strip())
            if match:
                fig_num = match.group(2)
                caption = (match.group(3) or "").strip() or None
                for fig in figures:
                    if fig["page_number"] == page.page_number and fig["figure_number"] is None:
                        fig["figure_number"] = f"Figure {fig_num}"
                        fig["caption"] = caption
                        break

    return figures
