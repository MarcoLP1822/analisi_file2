"""
Estrattore ODT
==============
Funzioni:
• extract_odt_properties
(la detailed_analysis viene già generata al suo interno)
"""

from __future__ import annotations

import io
from typing import Any

from odf.opendocument import load as load_odt
from odf.style import PageLayoutProperties
from odf.text import H as OdtHeading

from models import DetailedDocumentAnalysis, FontInfo, ImageInfo


def _parse_dimension(value: str | None) -> float:
    """Converte '21cm', '210mm', '8.5in' in centimetri."""
    if not value:
        return 0.0
    if "cm" in value:
        return float(value.replace("cm", ""))
    if "mm" in value:
        return float(value.replace("mm", "")) / 10
    if "in" in value:
        return float(value.replace("in", "")) * 2.54
    return float(value)


def extract_odt_properties(file_content: bytes) -> dict[str, Any]:
    doc = load_odt(io.BytesIO(file_content))

    # ------------- page layout -------------------------------------
    page_layouts = doc.getElementsByType(PageLayoutProperties)
    if not page_layouts:
        # fallback minimale
        return {
            "page_size": {"width_cm": 0, "height_cm": 0},
            "margins": {"top_cm": 0, "bottom_cm": 0, "left_cm": 0, "right_cm": 0},
            "has_toc": False,
            "headings": [],
            "detailed_analysis": DetailedDocumentAnalysis(),
        }

    pl = page_layouts[0]
    page_width = _parse_dimension(pl.getAttribute("fo:page-width"))
    page_height = _parse_dimension(pl.getAttribute("fo:page-height"))
    margin_top = _parse_dimension(pl.getAttribute("fo:margin-top"))
    margin_bottom = _parse_dimension(pl.getAttribute("fo:margin-bottom"))
    margin_left = _parse_dimension(pl.getAttribute("fo:margin-left"))
    margin_right = _parse_dimension(pl.getAttribute("fo:margin-right"))

    # ------------- heading / TOC -----------------------------------
    headings: list[str] = []
    for h in doc.getElementsByType(OdtHeading):
        if h.firstChild:
            headings.append(h.firstChild.data)

    has_toc = bool(headings)

    # ------------- colore & immagini -------------------------------
    from odf.draw import Image as OdtImage
    from odf.style import GraphicProperties, TextProperties

    image_count = len(doc.getElementsByType(OdtImage))
    has_color_pages = image_count > 0
    has_color_text = False
    colored_elements_count = image_count

    for prop in doc.getElementsByType(TextProperties):
        color = prop.getAttribute("fo:color")
        if color and color != "#000000":
            has_color_text = True
            colored_elements_count += 1

    for gp in doc.getElementsByType(GraphicProperties):
        fill_color = gp.getAttribute("draw:fill-color")
        if fill_color and fill_color != "#000000":
            has_color_pages = True
            colored_elements_count += 1

    detailed_analysis = DetailedDocumentAnalysis(
        fonts={"Default": FontInfo(sizes=[11.0], count=1)},
        images=ImageInfo(count=image_count, avg_size_kb=10.0) if image_count else None,
        line_spacing={"Default": 1.2},
        paragraph_count=len(headings),
        toc_structure=[
            {
                "level": str(h.getAttribute("text:outline-level") or "1"),
                "text": h.firstChild.data,
            }
            for h in doc.getElementsByType(OdtHeading)
            if h.firstChild
        ],
        metadata={},
        has_color_pages=has_color_pages,
        has_color_text=has_color_text,
        colored_elements_count=colored_elements_count,
    )

    return {
        "page_size": {"width_cm": page_width, "height_cm": page_height},
        "margins": {
            "top_cm": margin_top,
            "bottom_cm": margin_bottom,
            "left_cm": margin_left,
            "right_cm": margin_right,
        },
        "has_toc": has_toc,
        "headings": headings,
        "headers": [],
        "footnotes": [],
        "detailed_analysis": detailed_analysis,
    }
