"""
Regole di validazione atomiche.
Ogni funzione riceve `doc_props`, `spec`, più eventualmente `services`
e restituisce True (OK) o False (KO).

Le funzioni sono pure → facili da testare singolarmente.
"""

from __future__ import annotations

from typing import Any

from models import DocumentSpec

# --------------------------- helpers ------------------------------- #
_TOL_PAGE_CM = 0.6   # tolleranza dimensioni pagina
_TOL_MARGIN_CM = 0.5 # tolleranza margini


def page_size(doc: dict[str, Any], spec: DocumentSpec, services: dict[str, bool]) -> bool:
    if services.get("layout_service"):
        return True
    sz = doc["page_size"]
    return (
        abs(sz["width_cm"] - spec.page_width_cm) < _TOL_PAGE_CM
        and abs(sz["height_cm"] - spec.page_height_cm) < _TOL_PAGE_CM
    )


def format_consistency(doc: dict[str, Any], *_args) -> bool:
    return not doc.get("has_size_inconsistencies", False)


def margins(doc: dict[str, Any], spec: DocumentSpec, services: dict[str, bool]) -> bool:
    if services.get("layout_service"):
        return True
    m = doc["margins"]
    return (
        abs(m["top_cm"]    - spec.top_margin_cm)    < _TOL_MARGIN_CM
        and abs(m["bottom_cm"] - spec.bottom_margin_cm) < _TOL_MARGIN_CM
        and abs(m["left_cm"]   - spec.left_margin_cm)   < _TOL_MARGIN_CM
        and abs(m["right_cm"]  - spec.right_margin_cm)  < _TOL_MARGIN_CM
    )


def has_toc(doc: dict[str, Any], spec: DocumentSpec, *_a) -> bool:
    return not spec.requires_toc or doc["has_toc"]


def no_color_pages(doc: dict[str, Any], spec: DocumentSpec, *_a) -> bool:
    da = doc.get("detailed_analysis")
    if not spec.no_color_pages:
        return True
    return not (da and (da.has_color_pages or da.has_color_text))


def no_images(doc: dict[str, Any], spec: DocumentSpec, *_a) -> bool:
    da = doc.get("detailed_analysis")
    if not spec.no_images:
        return True
    return not (da and da.images and da.images.count)


def has_header(doc: dict[str, Any], spec: DocumentSpec, *_a) -> bool:
    return not spec.requires_header or bool(doc.get("headers"))


def has_footnotes(doc: dict[str, Any], spec: DocumentSpec, *_a) -> bool:
    return not spec.requires_footnotes or bool(doc.get("footnotes"))


def min_page_count(doc: dict[str, Any], spec: DocumentSpec, *_a) -> bool:
    return doc.get("page_count", 0) >= spec.min_page_count


def page_numbers_position(doc: dict[str, Any], *_a) -> bool:
    pos = doc.get("page_num_positions", [])
    if not pos:
        return False
    return all(p in ("center", "left", "right") for p in pos)
