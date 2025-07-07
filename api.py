"""
api.py  –  versione “FastAPI Light” senza MongoDB
-------------------------------------------------
* un solo flusso:  POST /api/validate‑order
* store in‑memory (utils.local_store) per conservare result + spec
* generazione PDF: POST /api/validation-reports/{id}
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Response, status, Request
from fastapi.responses import JSONResponse
from datetime import datetime
import logging
import os
from starlette.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder

# utilità locali
from utils.order_parser import parse_order
from utils.local_store import save_result, get_entry
from config import settings
from models import (
    DocumentSpec,
    ValidationResult,
    ReportFormat,
)

logger = logging.getLogger("document_validator")
api_router = APIRouter(prefix="/api")

# ------------------------------------------------------------------ #
# Root
# ------------------------------------------------------------------ #
@api_router.get("/", status_code=status.HTTP_200_OK)
async def root():
    return {"message": "Document Validator API — Lite", "version": "2.0.0"}


# ------------------------------------------------------------------ #
# VALIDAZIONE BASATA SUL TESTO DELL’ORDINE
# ------------------------------------------------------------------ #
@api_router.post("/validate-order", response_model=ValidationResult)
async def validate_with_order(
    request: Request,
    order_text: str = Form(...),
    file: UploadFile = File(...),
):
    # ─── IMPORT LOCALE per evitare il ciclo ───
    from server import process_document, validate_document

    try:
        # 1) parse ordine ------------------------------------------------
        parsed = parse_order(order_text)
        width_cm, height_cm = parsed["final_format_cm"]
        services = parsed["services"]

        # 2) specifica derivata -----------------------------------------
        spec = DocumentSpec(
            name="Specifica derivata dall’ordine",
            page_width_cm=width_cm,
            page_height_cm=height_cm,
            top_margin_cm=0,
            bottom_margin_cm=0,
            left_margin_cm=0,
            right_margin_cm=0,
            min_page_count=40,     # fisso
        )

        # 3) analisi documento ------------------------------------------
        file_bytes = await file.read()

        # --- controllo dimensione --------------------------------------
        if len(file_bytes) > settings.MAX_FILE_SIZE:
            max_mb = settings.MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(
                status_code=413,           # 413 Request Entity Too Large
                detail=f"File troppo grande: massimo {max_mb} MB."
            )

        ext = file.filename.split(".")[-1].lower()
        doc_props = await run_in_threadpool(process_document, file_bytes, ext)

        # 4) validazione dinamica ---------------------------------------
        validation = validate_document(doc_props, spec, services)

        # 5) build result + salva in memoria ----------------------------
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
        save_result(result, spec)              # in-memory store
        return result

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ex:
        logger.error(f"Errore in /validate-order: {ex}")
        raise HTTPException(status_code=500, detail="Errore interno")


# ------------------------------------------------------------------ #
# GENERAZIONE PDF DI REPORT
# ------------------------------------------------------------------ #
@api_router.post("/validation-reports/{validation_id}")
async def generate_report(
    validation_id: str,
    report_format: ReportFormat = ReportFormat(),
):
    # ─── IMPORT LOCALE per evitare il ciclo ───
    from server import generate_validation_report

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

# HEALTH CHECK (semplice, senza DB)
# ------------------------------------------------------------------ #
@api_router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "build": os.getenv("APP_BUILD", "dev"),
    }
