"""
Estrattore PDF
==============
Contiene:
• extract_pdf_properties
• extract_pdf_detailed_analysis
Usa PyPDF2, pdfplumber e PyMuPDF (fitz).

IMPORTANTE: non dipende da FastAPI né da nulla dell'API layer.
"""

from __future__ import annotations

import io
from typing import Any

import fitz  # PyMuPDF
import pdfplumber
import PyPDF2
from fastapi import HTTPException  # usata per errore formato

from models import DetailedDocumentAnalysis, FontInfo, ImageInfo

# ------------------------------------------------------------------ #
# helper privati
# ------------------------------------------------------------------ #
CM_PER_PT: float = 0.0352778


def _pick_box(page: PyPDF2._page.PageObject):  # type: ignore[attr-defined]
    """
    Ritorna TrimBox se presente, altrimenti CropBox, altrimenti MediaBox.
    """
    for attr in ("trimbox", "cropbox", "mediabox"):
        box = getattr(page, attr, None)
        if box is not None:
            return box
    return page.mediabox  # fallback estremo


# ------------------------------------------------------------------ #
# funzione pubblica principale
# ------------------------------------------------------------------ #
def extract_pdf_properties(file_content: bytes) -> dict[str, Any]:
    """
    Estrae le proprietà principali da un PDF:
    • formato pagina e coerenza
    • margini (TrimBox vs MediaBox)
    • posizione numero di pagina
    • heading/header/footer euristici
    • analisi dettagliata (font, immagini, colori…)
    """
    pdf_io = io.BytesIO(file_content)
    reader = PyPDF2.PdfReader(pdf_io)

    if not reader.pages:
        raise HTTPException(status_code=400, detail="PDF file has no pages")

    # ---------- formato pagina & inconsistenze ---------------------
    page_boxes: list[dict[str, float]] = []
    inconsistent_pages: list[dict[str, float]] = []

    for idx, pg in enumerate(reader.pages):
        box = _pick_box(pg)
        w_pt, h_pt = float(box.width), float(box.height)
        page_boxes.append(
            {"page": idx + 1, "width_cm": w_pt * CM_PER_PT, "height_cm": h_pt * CM_PER_PT}
        )

    ref_w, ref_h = page_boxes[0]["width_cm"], page_boxes[0]["height_cm"]
    for pb in page_boxes[1:]:
        if abs(pb["width_cm"] - ref_w) > 0.1 or abs(pb["height_cm"] - ref_h) > 0.1:
            inconsistent_pages.append(pb)

    # ---------- margini (pag. 1) -----------------------------------
    first_pg = reader.pages[0]
    trim, media = _pick_box(first_pg), first_pg.mediabox
    margins = {
        "top_cm": (float(media.upper_right[1]) - float(trim.upper_right[1])) * CM_PER_PT,
        "bottom_cm": (float(trim.lower_left[1]) - float(media.lower_left[1])) * CM_PER_PT,
        "left_cm": (float(trim.lower_left[0]) - float(media.lower_left[0])) * CM_PER_PT,
        "right_cm": (float(media.upper_right[0]) - float(trim.upper_right[0])) * CM_PER_PT,
    }

    # ---------- heading / TOC euristico & numeri pagina ------------
    headings: list[str] = []
    headers: list[str] = []
    footnotes: list[str] = []
    page_num_positions: list[str] = []

    with pdfplumber.open(pdf_io) as pdf:
        h_pt = pdf.pages[0].height
        w_pt = pdf.pages[0].width
        bottom_th = 56  # ~2 cm

        for idx, p in enumerate(pdf.pages):
            txt = (p.extract_text() or "").lower()

            if any(k in txt for k in ("indice", "table of contents", "contents", "toc", "sommario")):
                headings.append("TOC detected")

            if idx < 3 and txt:
                lines = txt.splitlines()
                headers.append(lines[0].strip())
                footnotes.append(lines[-1].strip())

            # rileva numero pagina
            pos = "missing"
            for w in p.extract_words(keep_blank_chars=False, use_text_flow=True):
                if w["text"].strip().isdigit() and int(w["text"]) == idx + 1:
                    if w["bottom"] < h_pt - bottom_th:  # non nel footer
                        continue
                    cx = (w["x0"] + w["x1"]) / 2
                    if abs(cx - w_pt / 2) <= w_pt * 0.15:
                        pos = "center"
                    elif cx < w_pt * 0.25:
                        pos = "left"
                    elif cx > w_pt * 0.75:
                        pos = "right"
                    break
            page_num_positions.append(pos)

    # ---------- analisi dettagliata --------------------------------
    detailed_analysis = extract_pdf_detailed_analysis(file_content)

    return {
        "page_size": {"width_cm": ref_w, "height_cm": ref_h},
        "margins": margins,
        "has_toc": bool(headings),
        "headings": headings,
        "headers": headers,
        "footnotes": footnotes,
        "detailed_analysis": detailed_analysis,
        "page_count": len(reader.pages),
        "page_num_positions": page_num_positions,
        "inconsistent_pages": inconsistent_pages,
        "has_size_inconsistencies": bool(inconsistent_pages),
    }


# ------------------------------------------------------------------ #
# analisi approfondita
# ------------------------------------------------------------------ #
def extract_pdf_detailed_analysis(file_content: bytes) -> DetailedDocumentAnalysis:
    """
    Raccoglie info su:
    • font (con occorrenze per size)
    • immagini (conteggio + peso medio)
    • colore (pagine con colore, testo colorato)
    • TOC, paragrafi, metadati
    """
    pdf_io = io.BytesIO(file_content)
    doc = fitz.open(stream=pdf_io, filetype="pdf")

    fonts: dict[str, FontInfo] = {}
    toc_structure: list[dict[str, str]] = []
    paragraph_count = 0
    image_count = 0
    total_image_size = 0
    color_pages: set[int] = set()
    has_color_text = False

    # ---- metadati --------------------------------------------------
    metadata = {
        k: str(v)
        for k, v in doc.metadata.items()
        if v and k not in ("format", "encryption")
    }

    # ---- pagine ----------------------------------------------------
    for page_num, page in enumerate(doc):
        paragraph_count += len(page.get_text("blocks"))

        page_is_color = False

        # immagini
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                base = doc.extract_image(xref)
                if base:
                    image_count += 1
                    total_image_size += len(base["image"])
                    page_is_color = True
            except Exception:
                pass  # ignore extract errors

        # sample pixel grigi / colore
        if not page_is_color:
            pix = page.get_pixmap(samples=8, colorspace=fitz.csRGB)
            for px in pix.samples:
                if px[0] != px[1] or px[1] != px[2]:
                    page_is_color = True
                    break

        # font & colore testo
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                for sp in ln.get("spans", []):
                    fname = sp["font"]
                    fsize = round(float(sp["size"]), 1)

                    fi = fonts.setdefault(fname, FontInfo(sizes=[], count=0, size_counts={}))
                    fi.count += 1
                    if fsize not in fi.sizes:
                        fi.sizes.append(fsize)
                    fi.size_counts[fsize] = fi.size_counts.get(fsize, 0) + 1

                    if sp["color"] not in (0, 0x000000):
                        has_color_text = True
                        page_is_color = True

        if page_is_color:
            color_pages.add(page_num)

    # ---- TOC -------------------------------------------------------
    toc = doc.get_toc()
    for lvl, title, _ in toc or []:
        toc_structure.append({"level": str(lvl), "text": title})

    image_info = (
        ImageInfo(count=image_count, avg_size_kb=round((total_image_size / image_count) / 1024, 2))
        if image_count
        else None
    )

    return DetailedDocumentAnalysis(
        fonts=fonts,
        images=image_info,
        line_spacing={"Default": 1.2},
        paragraph_count=paragraph_count,
        toc_structure=toc_structure,
        metadata=metadata,
        has_color_pages=bool(color_pages),
        has_color_text=has_color_text,
        colored_elements_count=len(color_pages),
    )
