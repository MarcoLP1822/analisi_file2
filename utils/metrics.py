"""
utils.metrics
=============
Definisce metriche custom Prometheus.
"""

from prometheus_client import Counter

# Totale validazioni raggruppate per esito
VALIDATION_RESULT = Counter(
    "validation_result_total",
    "Conteggio validazioni documento per esito",
    ["status"],          # label: ok | ko | error
)
