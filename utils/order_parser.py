# utils/order_parser.py
import re

# Mappa «parola chiave» ➔ nome interno del servizio
SERVICES_KEYWORDS = {
    r"impaginazione": "layout_service",
    # in futuro potrai aggiungere altri servizi qui
}

# ------------------------------------------------------------------ #
def parse_order(text: str) -> dict:
    """
    Estrae dal testo libero dell'ordine:
    • formato finale in cm (larghezza, altezza)                es. 17x24
    • dizionario servizi acquistati -> bool
    """
    # 1) servizi
    services = {v: False for v in SERVICES_KEYWORDS.values()}
    for pattern, key in SERVICES_KEYWORDS.items():
        if re.search(pattern, text, re.I):
            services[key] = True

    # 2) formato finale (accetta 'Formato: 17x24', 'Formato 17 x 24', ecc.)
    m = re.search(
        r"Formato\s*:?\s*([0-9]+(?:[,\.][0-9]+)?)\s*[x×]\s*([0-9]+(?:[,\.][0-9]+)?)",
        text,
        re.I,
    )
    if not m:
        raise ValueError("Formato finale non trovato nel testo dell’ordine.")

    w_cm = float(m.group(1).replace(",", "."))
    h_cm = float(m.group(2).replace(",", "."))

    return {
        "final_format_cm": (w_cm, h_cm),
        "services": services,
    }
