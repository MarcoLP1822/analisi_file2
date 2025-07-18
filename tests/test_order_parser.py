# tests/test_order_parser.py
from utils.order_parser import ParsedOrder, parse_order


def test_parse_order_format_and_service():
    text = "Formato: 17x24\n1x Servizio impaginazione testo"
    result: ParsedOrder = parse_order(text)

    # formato corretto
    assert result["final_format_cm"] == (17.0, 24.0)

    # servizio rilevato
    assert result["services"]["layout_service"] is True
