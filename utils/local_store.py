# utils/local_store.py
from typing import Dict, TypedDict
from models import ValidationResult, DocumentSpec

class _Entry(TypedDict):
    result: ValidationResult
    spec:   DocumentSpec

_storage: Dict[str, _Entry] = {}

# --------------------------------------------------------------- #
def save_result(result: ValidationResult, spec: DocumentSpec) -> None:
    _storage[result.id] = {"result": result, "spec": spec}

def get_entry(result_id: str) -> _Entry | None:
    return _storage.get(result_id)
