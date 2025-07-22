"""
Core validation orchestrator.
Combina le singole regole definite in rules.py e restituisce:
{
    "validations": {nome_regola: bool, ...},
    "is_valid": bool
}
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from models import DocumentSpec

from . import rules

# mappa “nome -> funzione”  (l’ordine rimane stabile in Py 3.7+)
# tipo per ogni funzione-regola: (doc_props, spec, services) -> bool
RuleFunc = Callable[[dict[str, Any], DocumentSpec, dict[str, bool]], bool]

_RULES: dict[str, RuleFunc] = {
    "page_size":              rules.page_size,
    "format_consistency":     rules.format_consistency,
    "margins":                rules.margins,
    "has_toc":                rules.has_toc,
    "no_color_pages":         rules.no_color_pages,
    "no_images":              rules.no_images,
    "has_header":             rules.has_header,
    "has_footnotes":          rules.has_footnotes,
    "min_page_count":         rules.min_page_count,
    "page_numbers_position":  rules.page_numbers_position,
}

def validate_document(
    doc_props: dict[str, Any],
    spec: DocumentSpec,
    services: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Esegue tutte le regole in _RULES.
    Ritorna dict con esito di ogni regola + boolean complessivo.
    """
    if not doc_props or "page_size" not in doc_props:
        raise HTTPException(status_code=400, detail="doc_props non validi")

    services = services or {}

    validations: dict[str, bool] = {}
    for name, fn in _RULES.items():
        try:
            validations[name] = fn(doc_props, spec, services)  # type: ignore[arg-type]
        except Exception:
            # qualsiasi errore interno viene considerato KO
            validations[name] = False

    return {
        "validations": validations,
        "is_valid": all(validations.values()),
    }
