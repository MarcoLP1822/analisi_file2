"""
Dispatcher `process_document`
=============================
Sceglie l'estrattore corretto in base all'estensione.
"""

from typing import Any

from fastapi import HTTPException

from utils.conversion import convert_to_pdf_via_lo, extract_pdf_page_count

from .docx import extract_docx_properties
from .odt import extract_odt_properties
from .pdf import extract_pdf_properties


def process_document(file_content: bytes, file_format: str) -> dict[str, Any]:
    """
    Estrae le proprietà di un documento, calcolando page_count se serve.

    Supporta: pdf, docx, odt, doc (binario).

    Per doc/docx/odt converte in PDF con LibreOffice per ricavare il numero
    di pagine.
    """
    fmt = file_format.lower()

    # ---------- .DOC binario ----------------------------------------
    if fmt == "doc":
        pdf_bytes = convert_to_pdf_via_lo(file_content, "doc")
        return extract_pdf_properties(pdf_bytes)

    # ---------- .DOCX -----------------------------------------------
    if fmt == "docx":
        doc_props = extract_docx_properties(file_content)
        pdf_bytes = convert_to_pdf_via_lo(file_content, "docx")
        doc_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return doc_props

    # ---------- .ODT -------------------------------------------------
    if fmt == "odt":
        odt_props = extract_odt_properties(file_content)
        pdf_bytes = convert_to_pdf_via_lo(file_content, "odt")
        odt_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return odt_props

    # ---------- .PDF -------------------------------------------------
    if fmt == "pdf":
        return extract_pdf_properties(file_content)

    raise HTTPException(status_code=400, detail=f"Unsupported file format: {file_format}")
