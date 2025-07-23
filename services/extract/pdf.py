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
    Analisi PDF:
    • raccoglie font, paragrafi, TOC, metadati
    • rileva immagini e testo colorato
    • calcola il numero di *pagine* che contengono elementi a colori
      (colored_elements_count diventa pages_with_color)
    """


    pdf_io = io.BytesIO(file_content)
    pdf_doc = fitz.open(stream=pdf_io, filetype="pdf")

    fonts: dict[str, FontInfo] = {}
    toc_structure: list[dict[str, str]] = []
    paragraph_count = 0
    image_count = 0
    total_image_size = 0

    color_pages: set[int] = set()
    has_color_text = False

    # -------- metadati ------------------------------------------------
    metadata = {k: str(v) for k, v in pdf_doc.metadata.items() if v and k not in ("format", "encryption")}

    # -------- scorre pagine ------------------------------------------
    for page_num, page in enumerate(pdf_doc):
        # paragrafi approssimati
        paragraph_count += len(page.get_text("blocks"))

        page_is_color = False  # flag locale

        # immagini
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                base_image = pdf_doc.extract_image(xref)
                if base_image:
                    image_count += 1
                    total_image_size += len(base_image["image"])
                    page_is_color = True
            except Exception:
                pass

        # pixel color check (fallback a bassa risoluzione)
        if not page_is_color:
            # Render molto piccolo (scala 0.1) per ridurre i byte
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(0.1, 0.1), colorspace=fitz.csRGB)
            except TypeError:
                # vecchie versioni non hanno colorspace: usiamo default
                pix = page.get_pixmap(matrix=fitz.Matrix(0.1, 0.1))

            # pix.samples è un buffer di byte: RGBRGBRGB...
            step = pix.n  # numero di canali (3 se RGB)
            data = pix.samples  # type: ignore[arg-type]

            for i in range(0, len(data), step):
                # se è RGB, confronta i 3 canali
                if step >= 3:
                    r, g, b = data[i], data[i + 1], data[i + 2]
                    if not (r == g == b):
                        page_is_color = True
                        break

        # font & testo colorato
        for span in page.get_text("dict")["blocks"]:
            for l in span.get("lines", []):
                for s in l.get("spans", []):
                    font_name = s["font"]
                    font_size = round(float(s["size"]), 1)

                    # aggiorna font dict
                    fi = fonts.setdefault(font_name, FontInfo(sizes=[], count=0, size_counts={}))
                    fi.count += 1
                    if font_size not in fi.sizes:
                        fi.sizes.append(font_size)
                    fi.size_counts[font_size] = fi.size_counts.get(font_size, 0) + 1

                    # colore RGB
                    if s["color"] not in (0, 0x000000):
                        has_color_text = True
                        page_is_color = True

        if page_is_color:
            color_pages.add(page_num)

    # -------- TOC -----------------------------------------------------
    toc = pdf_doc.get_toc()
    if toc:
        for level, title, _ in toc:
            toc_structure.append({"level": str(level), "text": title})

    # -------- immagini info ------------------------------------------
    image_info = None
    if image_count:
        image_info = ImageInfo(
            count=image_count,
            avg_size_kb=round((total_image_size / image_count) / 1024, 2),
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
        colored_elements_count=len(color_pages),  # = pagine con colore
    )