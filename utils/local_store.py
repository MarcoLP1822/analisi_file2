# utils/local_store.py
"""
Mini-store in-memory: ora thread-safe.
Se in futuro userai Redis o un DB potrai rimuovere il lock.
"""
from threading import Lock  # 👈 nuovo
from typing import TypedDict

from models import DocumentSpec, ValidationResult


class _Entry(TypedDict):
    result: ValidationResult
    spec:   DocumentSpec

_storage: dict[str, _Entry] = {}
_lock = Lock()                                # 👈 nuovo

# --------------------------------------------------------------- #
def save_result(result: ValidationResult, spec: DocumentSpec) -> None:
    """Salva (o sovrascrive) l’esito di una validazione."""
    with _lock:                               # 👈 protezione
        _storage[result.id] = {"result": result, "spec": spec}

def get_entry(result_id: str) -> _Entry | None:
    """Recupera risultato + spec; None se l’id non esiste."""
    with _lock:                               # 👈 protezione
        return _storage.get(result_id)
