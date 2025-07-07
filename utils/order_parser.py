# utils/order_parser.py
"""
Parsing del testo dell’ordine:
• rileva i servizi acquistati tramite keyword
• estrae il formato finale (larghezza × altezza in cm)
"""
from __future__ import annotations
import re
import unicodedata
from typing import Dict

# Mappa «parola chiave» ➔ nome interno del servizio
SERVICES_KEYWORDS: Dict[str, str] = {
    r"impaginazione": "layout_service",
    # aggiungi altre keyword → servizio qui
}

# ------------------------------------------------------------------ #
def _normalize(text: str) -> str:
    """
    • Unicode NFKC (es. '×' → 'x', '㎝' → 'cm')
    • NBSP → spazio normale
    • Tab/nuova linea multiple → spazio singolo
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00A0", " ")          # non-breaking space
    text = re.sub(r"\s+", " ", text)            # spazi consecutivi
    return text.strip()

# ------------------------------------------------------------------ #
def parse_order(text: str) -> dict:
    """
    Ritorna un dizionario:
    {
        "final_format_cm": (larghezza_cm, altezza_cm),
        "services": { nome_servizio: bool, ... }
    }
    Lancia ValueError se il formato non viene trovato.
    """
    text_norm = _normalize(text)

    # 1) servizi -----------------------------------------------------
    services = {v: False for v in SERVICES_KEYWORDS.values()}
    for pattern, key in SERVICES_KEYWORDS.items():
        if re.search(pattern, text_norm, re.I):
            services[key] = True

    # 2) formato finale ---------------------------------------------
    fmt_re = re.compile(
        r"formato\s*:?\s*"
        r"([0-9]+(?:[.,][0-9]+)?)"      # larghezza
        r"\s*[x×\*]\s*"                 # separatore: x, × o *
        r"([0-9]+(?:[.,][0-9]+)?)",     # altezza
        flags=re.I,
    )

    m = fmt_re.search(text_norm)
    if not m:
        raise ValueError(
            "Formato finale non trovato nel testo dell’ordine "
            "(usa ad es. 'Formato: 17x24')."
        )

    w_cm = float(m.group(1).replace(",", "."))
    h_cm = float(m.group(2).replace(",", "."))

    return {
        "final_format_cm": (w_cm, h_cm),
        "services": services,
    }
