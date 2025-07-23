"""
Versione asincrona del dispatcher di estrazione proprietà.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from utils.async_conversion import convert_to_pdf_via_lo_async
from utils.conversion import extract_pdf_page_count

from .docx import extract_docx_properties
from .odt import extract_odt_properties
from .pdf import extract_pdf_properties


async def process_document_async(file_content: bytes, file_format: str) -> dict[str, Any]:
    fmt = file_format.lower()

    # ---------- .DOC binario ----------------------------------------
    if fmt == "doc":
        pdf_bytes = await convert_to_pdf_via_lo_async(file_content, "doc")
        return extract_pdf_properties(pdf_bytes)

    # ---------- .DOCX -----------------------------------------------
    if fmt == "docx":
        doc_props = extract_docx_properties(file_content)
        pdf_bytes = await convert_to_pdf_via_lo_async(file_content, "docx")
        doc_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return doc_props

    # ---------- .ODT -------------------------------------------------
    if fmt == "odt":
        odt_props = extract_odt_properties(file_content)
        pdf_bytes = await convert_to_pdf_via_lo_async(file_content, "odt")
        odt_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return odt_props

    # ---------- .PDF -------------------------------------------------
    if fmt == "pdf":
        return extract_pdf_properties(file_content)

    raise HTTPException(status_code=400, detail=f"Unsupported file format: {file_format}")
