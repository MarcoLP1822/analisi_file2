"""Public API del sotto-package extract."""

from .async_base import process_document_async  # noqa: F401
from .base import process_document  # noqa: F401
from .docx import extract_docx_properties  # noqa: F401
from .odt import extract_odt_properties  # noqa: F401
from .pdf import extract_pdf_properties  # noqa: F401

__all__ = [
    "process_document",
    "process_document_async",
    "extract_pdf_properties",
    "extract_docx_properties",
    "extract_odt_properties",
]
