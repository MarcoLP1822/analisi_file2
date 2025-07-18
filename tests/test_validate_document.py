# tests/test_validate_document.py
from models import DocumentSpec
from services.document import validate_document


def test_validate_page_size_ok():
    """
    Verifica che, con proprietà coerenti (dimensioni pagina, margini
    e numero pagina nel footer), la validazione risulti complessivamente OK.
    """
    # Proprietà documento (mock minimale, ma completo)
    doc_props = {
        "page_size": {"width_cm": 17.0, "height_cm": 24.0},
        "margins":   {"top_cm": 0, "bottom_cm": 0, "left_cm": 0, "right_cm": 0},
        "has_toc":   False,
        "page_num_positions": ["center"],   # ← chiave mancante prima
    }

    spec = DocumentSpec(
        name="Spec test",
        page_width_cm=17.0,
        page_height_cm=24.0,
        top_margin_cm=0,
        bottom_margin_cm=0,
        left_margin_cm=0,
        right_margin_cm=0,
    )

    result = validate_document(doc_props, spec)

    assert result["is_valid"] is True
    assert result["validations"]["page_size"] is True
    assert result["validations"]["page_numbers_position"] is True
