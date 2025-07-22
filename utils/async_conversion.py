"""
Wrapper async per la conversione via LibreOffice.

Usa asyncio.to_thread per spostare la system-call in un thread separato,
lasciando libero l'event-loop di FastAPI.
"""

from __future__ import annotations

import asyncio
from typing import Final

from utils.conversion import convert_to_pdf_via_lo

# Timeout max (secondi) – lo stesso che usiamo nel wrapper sync
_DEFAULT_TO_THREAD_TIMEOUT: Final[int] = 90


async def convert_to_pdf_via_lo_async(
    src_bytes: bytes,
    ext: str,
    *,
    timeout: int | None = _DEFAULT_TO_THREAD_TIMEOUT,
) -> bytes:
    """
    Versione asincrona di `convert_to_pdf_via_lo`.

    Parameters
    ----------
    src_bytes : bytes
        Contenuto del file originale.
    ext : str
        Estensione (doc, docx, odt).
    timeout : int | None
        Massimo tempo di attesa della conversione.

    Returns
    -------
    bytes
        Il PDF risultante.
    """
    return await asyncio.wait_for(
        asyncio.to_thread(convert_to_pdf_via_lo, src_bytes, ext),
        timeout=timeout,
    )
