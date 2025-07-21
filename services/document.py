# services/document.py
"""
Funzioni di alto livello per:
1. Estrarre le proprietà di un documento (process_document)
2. Validarlo rispetto a una DocumentSpec (validate_document)
Il codice è copiato da server.py (nessuna logica cambiata).
"""
from typing import Any

from fastapi import HTTPException

from models import DocumentSpec
from utils.conversion import (
    convert_to_pdf_via_lo,
    extract_pdf_page_count,
)


# ↓↓↓  === copia integrale delle vecchie funzioni === ↓↓↓
# ------------------------------------------------------------------ #
def process_document(file_content: bytes, file_format: str) -> dict[str, Any]:
    """
    Estrae le proprietà del documento e, dove serve, calcola anche page_count
    convertendo prima in PDF con LibreOffice. Supporta doc, docx, odt e pdf.
    """
    from server import (
        extract_docx_properties,
        extract_odt_properties,
        extract_pdf_properties,
    )
    
    fmt = file_format.lower()

    # ---------- .DOC binario ----------------------------------------
    if fmt == "doc":
        pdf_bytes = convert_to_pdf_via_lo(file_content, "doc")
        pdf_props = extract_pdf_properties(pdf_bytes)
        return pdf_props

    # ---------- .DOCX ----------------------------------------------
    if fmt == "docx":
        doc_props = extract_docx_properties(file_content)
        pdf_bytes = convert_to_pdf_via_lo(file_content, "docx")
        doc_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return doc_props

    # ---------- .ODT -----------------------------------------------
    if fmt == "odt":
        odt_props = extract_odt_properties(file_content)
        pdf_bytes = convert_to_pdf_via_lo(file_content, "odt")
        odt_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return odt_props

    # ---------- .PDF ------------------------------------------------
    if fmt == "pdf":
        pdf_props = extract_pdf_properties(file_content)
        return pdf_props

    raise HTTPException(status_code=400, detail=f"Unsupported file format: {file_format}")


# ------------------------------------------------------------------ #
def validate_document(
    doc_props: dict[str, Any],
    spec: DocumentSpec,
    services: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Ritorna:
    {
        "validations": {check_name: bool, ...},
        "is_valid": bool,
    }
    Alcuni check vengono disattivati se presenti servizi acquistati.
    """
    services = services or {}
    validations: dict[str, bool] = {}

    # ─── Dimensioni pagina ──────────────────────────────────────────
    if services.get("layout_service"):
        validations["page_size"] = True
    else:
        pw_ok = abs(doc_props["page_size"]["width_cm"]  - spec.page_width_cm)  < 0.6
        ph_ok = abs(doc_props["page_size"]["height_cm"] - spec.page_height_cm) < 0.6
        validations["page_size"] = pw_ok and ph_ok

    # ─── Coerenza formato fra pagine/sezioni ────────────────────────
    validations["format_consistency"] = not doc_props.get(
        "has_size_inconsistencies", False
    )

    # ─── Margini ────────────────────────────────────────────────────
    if services.get("layout_service"):
        validations["margins"] = True
    else:
        m = doc_props["margins"]
        top_ok    = abs(m["top_cm"]    - spec.top_margin_cm)    < 0.5
        bottom_ok = abs(m["bottom_cm"] - spec.bottom_margin_cm) < 0.5
        left_ok   = abs(m["left_cm"]   - spec.left_margin_cm)   < 0.5
        right_ok  = abs(m["right_cm"]  - spec.right_margin_cm)  < 0.5
        validations["margins"] = top_ok and bottom_ok and left_ok and right_ok

    # ─── TOC, colori, immagini, header, footnote ────────────────────
    validations["has_toc"]        = not spec.requires_toc or doc_props["has_toc"]
    da = doc_props.get("detailed_analysis")
    validations["no_color_pages"] = (
        not spec.no_color_pages or not (da and (da.has_color_pages or da.has_color_text))
    )
    validations["no_images"]      = (
        not spec.no_images or not (da and da.images and da.images.count)
    )
    validations["has_header"]     = (
        not spec.requires_header or bool(doc_props.get("headers"))
    )
    validations["has_footnotes"]  = (
        not spec.requires_footnotes or bool(doc_props.get("footnotes"))
    )

    # ─── Pagine minime ──────────────────────────────────────────────
    validations["min_page_count"] = (
        doc_props.get("page_count", 0) >= spec.min_page_count
    )

    # ─── Numerazione pagine ─────────────────────────────────────────
    page_nums = doc_props.get("page_num_positions", [])

    if page_nums:
        page_number_valid = all(p in ("center", "left", "right") for p in page_nums)
    else:
        # nessuna numerazione rilevata = KO (adatta a tua policy)
        page_number_valid = False

    validations["page_numbers_position"] = page_number_valid

    # ─── Esito complessivo ──────────────────────────────────────────
    is_valid = all(validations.values())
    return {"validations": validations, "is_valid": is_valid}
