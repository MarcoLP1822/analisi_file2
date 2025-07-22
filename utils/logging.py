"""
utils.logging
=============
Configura structlog in modalità JSON (chiavi snake_case) + handler fallback
per librerie che usano logging standard.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_JSON_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "indent": None,
    "separators": (",", ":"),
    "sort_keys": False,
    "default": str,
}

def configure(level: str | int = "INFO") -> None:
    """
    Inizializza `logging` e `structlog`.
    Call una volta all’avvio.
    """
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(message)s",          # il formato reale lo decide structlog
    )

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,   # eccezioni → key exc_info
            structlog.processors.JSONRenderer(**_JSON_KWARGS),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """
    Restituisce un logger structlog configurato con il nome specificato.
    """
    return structlog.get_logger(name)
