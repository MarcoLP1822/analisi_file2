"""
api.py  –  versione “FastAPI Light” senza MongoDB
-------------------------------------------------
Flussi esposti (prefisso /api):

* POST /validate-order
    Valida un file in base al testo dell’ordine e salva l’esito in-memory.

* POST /validation-reports/{validation_id}
    Rende un PDF riassuntivo dell’esito appena validato.

* POST /zendesk-ticket
    Crea un ticket Zendesk con commento + PDF in allegato per il cliente.

* GET  /health
    Health-check basilare (nessun DB).

Gli esiti di validazione vengono mantenuti in RAM tramite utils.local_store.
"""

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Response,
    status,
    Request,
)
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from datetime import datetime
import logging
import os
import requests                          # per catch HTTPError Zendesk
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr

# utilità locali
from utils.order_parser import parse_order
from utils.local_store import save_result, get_entry
from config import settings
from models import DocumentSpec, ValidationResult, ReportFormat

logger = logging.getLogger("document_validator")
api_router = APIRouter(prefix="/api")

# ------------------------------------------------------------------ #
# ROOT (info versione)
# ------------------------------------------------------------------ #
@api_router.get("/", status_code=status.HTTP_200_OK)
async def root():
    return {"message": "Document Validator API — Lite", "version": "2.1.0"}


# ------------------------------------------------------------------ #
# 1) VALIDAZIONE BASATA SUL TESTO DELL’ORDINE
# ------------------------------------------------------------------ #
@api_router.post("/validate-order", response_model=ValidationResult)
async def validate_with_order(
    request: Request,
    order_text: str = Form(...),
    file: UploadFile = File(...),
):
    # import locali (evita import circolari)
    from server import process_document, validate_document

    try:
        # --- 1. parse testo ordine -----------------------------------
        parsed = parse_order(order_text)
        width_cm, height_cm = parsed["final_format_cm"]
        services = parsed["services"]

        # --- 2. definisci la specifica “derivata” --------------------
        spec = DocumentSpec(
            name="Specifica derivata dall’ordine",
            page_width_cm=width_cm,
            page_height_cm=height_cm,
            top_margin_cm=0,
            bottom_margin_cm=0,
            left_margin_cm=0,
            right_margin_cm=0,
            min_page_count=40,   # soglia fissa demo
        )

        # --- 3. leggi bytes e check dimensione -----------------------
        file_bytes = await file.read()
        if len(file_bytes) > settings.MAX_FILE_SIZE:
            max_mb = settings.MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"File troppo grande: massimo {max_mb} MB.",
            )

        # --- 4. estrai proprietà documento ---------------------------
        ext = file.filename.split(".")[-1].lower()
        doc_props = await run_in_threadpool(process_document, file_bytes, ext)

        # --- 5. validazione dinamica ---------------------------------
        validation = validate_document(doc_props, spec, services)

        # --- 6. serializza risultato e salva in memoria --------------
        result = ValidationResult(
            document_name=file.filename,
            spec_id=spec.id,
            spec_name=spec.name,
            file_format=ext,
            validations=validation["validations"],
            is_valid=validation["is_valid"],
            detailed_analysis=doc_props.get("detailed_analysis"),
            raw_props=jsonable_encoder(doc_props),
        )
        save_result(result, spec)
        return result

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ex:
        logger.error(f"Errore in /validate-order: {ex}")
        raise HTTPException(status_code=500, detail="Errore interno")


# ------------------------------------------------------------------ #
# 2) GENERAZIONE PDF DI REPORT
# ------------------------------------------------------------------ #
@api_router.post("/validation-reports/{validation_id}")
async def generate_report(
    validation_id: str,
    report_format: ReportFormat = ReportFormat(),
):
    from server import generate_validation_report  # import locale

    entry = get_entry(validation_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Validation result not found")

    validation_result: ValidationResult = entry["result"]
    spec: DocumentSpec = entry["spec"]

    pdf_report = generate_validation_report(validation_result, spec, report_format)

    return Response(
        content=pdf_report,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=validation_report_{validation_id}.pdf"
        },
    )


# ------------------------------------------------------------------ #
# 3) CREAZIONE TICKET ZENDESK CON PDF ALLEGATO
# ------------------------------------------------------------------ #
class ZendeskPayload(BaseModel):
    email: EmailStr        # destinatario originale
    message: str           # testo e-mail preparato dal front-end
    validation_id: str     # id risultato già salvato


@api_router.post("/zendesk-ticket")
async def zendesk_ticket(payload: ZendeskPayload):
    """
    • recupera il risultato di validazione
    • genera il PDF
    • chiama send_ticket_to_zendesk() per upload + ticket
    """
    entry = get_entry(payload.validation_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Validation ID non trovato")

    from server import generate_validation_report, send_ticket_to_zendesk

    pdf_bytes = generate_validation_report(
        entry["result"], entry["spec"], ReportFormat()
    )

    subject = f"Esito validazione – {entry['result'].document_name}"
    body = f"{payload.message}\n\nCliente origine: {payload.email}"

    try:
        ticket_id = send_ticket_to_zendesk(
            subject,
            body,
            pdf_bytes,
            f"validation_{payload.validation_id}.pdf",
            requester_email=payload.email,
        )
        return {"status": "ok", "ticket_id": ticket_id}
    except requests.HTTPError as e:
        logger.error(f"Zendesk API error: {e}")
        raise HTTPException(
            status_code=502, detail=f"Errore Zendesk {e.response.status_code}"
        )


# ------------------------------------------------------------------ #
# 4) HEALTH CHECK
# ------------------------------------------------------------------ #
@api_router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "build": os.getenv("APP_BUILD", "dev"),
    }
