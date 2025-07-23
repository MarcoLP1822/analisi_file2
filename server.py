# ────────────────────────────────────────────────────────────────
# server.py – sezione import, settings, logging, app, /metrics
# ────────────────────────────────────────────────────────────────
from __future__ import annotations

# ========== Librerie standard ==========
import io
import json
import os
import sys
from typing import cast

# ========== Terze parti ==========
import requests
from fastapi import APIRouter, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext

try:
    from prometheus_fastapi_instrumentator import Instrumentator
except ImportError:
    Instrumentator = None  # type: ignore[assignment]
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table

# ========== Import locali ==========
from config import Settings
from models import (
    DocumentSpec,
    ReportFormat,
    ValidationResult,
)
from utils.logging import configure as configure_logging  # funzione creata in utils/logging.py

# ========== Impostazioni & logging ==========
settings = Settings()

# CORS – origini consentite
origins = settings.allowed_origins_list

# Inizializza structlog (JSON su stdout) e ottieni il logger
configure_logging(settings.LOG_LEVEL)
from utils.logging import get_logger

log = get_logger("document_validator")

# ========== Sicurezza baseline ==========
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# ========== FastAPI app ==========
app = FastAPI(
    title="Document Validator API",
    description="API for validating and analyzing documents against specifications",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ========== Prometheus /metrics ==========
if Instrumentator:
    Instrumentator().instrument(app).expose(app, include_in_schema=False)
    
# Funzioni di autenticazione e sicurezza
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ──────────────────────────────────────────────────────────────────
#  GENERATE PDF – versione “client-friendly”
# ──────────────────────────────────────────────────────────────────
def generate_validation_report(
    validation_result: ValidationResult,
    spec: DocumentSpec,
    report_format: ReportFormat,
) -> bytes:
    import datetime
    import pathlib

    from reportlab.platypus import (
        HRFlowable,
        PageBreak,
    )

    # ── palette aziendale ─────────────────────────────────────────
    GREEN   = colors.HexColor("#198754")
    RED     = colors.HexColor("#d32f2f")
    ACCENT  = colors.HexColor("#0d6efd")     # blu Bootstrap
    BG_HEAD = colors.HexColor("#f2f4f6")     # grigio molto chiaro

    # ── helper: converte Color → '#RRGGBB' ────────────────────────
    def hex_(c):
        """ReportLab Color → HEX string '#RRGGBB'."""
        return f"#{c.hexval()[2:]}"        # '0xRRGGBB' → '#RRGGBB'


    # ── logo opzionale (PNG trasparente 200×60) ───────────────────
    LOGO_PATH = pathlib.Path(__file__).parent / "static" / "logo.png"
    logo_present = LOGO_PATH.exists()

    # ── buffer in memoria ─────────────────────────────────────────
    buff = io.BytesIO()
    doc  = SimpleDocTemplate(
        buff,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "TitleXL",
            parent=styles["Title"],
            fontSize=24,
            textColor=ACCENT,
            alignment=TA_CENTER,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            "Small",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
        )
    )

    elements = []

    # ───────────────────── 1) COPERTINA ───────────────────────────
    if logo_present:
        elements.append(
            Image(str(LOGO_PATH), width=6 * cm, height=2 * cm, hAlign="CENTER")
        )
        elements.append(Spacer(1, 0.4 * cm))

    elements.append(
        Paragraph("Document Validation Report", styles["TitleXL"])
    )
    elements.append(
        Paragraph(
            datetime.datetime.utcnow().strftime("%d %B %Y, %H:%M UTC"),
            styles["Small"],
        )
    )
    elements.append(Spacer(1, 1.2 * cm))

    # riquadro riassuntivo
    status_txt  = "CONFORME" if validation_result.is_valid else "NON CONFORME"
    status_col  = GREEN if validation_result.is_valid else RED

    status_cell = Paragraph(
        f"<b><font color='{hex_(status_col)}'>{status_txt}</font></b>",
        styles["Normal"],
    )

    summary_tbl = Table(
        [
            ["Documento", validation_result.document_name],
            ["Risultato", status_cell],          # ← usa Paragraph
            ["Specifica", spec.name],
        ],
        colWidths=[4 * cm, 11 * cm],
        hAlign="LEFT",
        style=[
            ("BACKGROUND", (0, 0), (-1, 0), BG_HEAD),
            ("BACKGROUND", (0, 2), (-1, 2), BG_HEAD),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BOX", (0, 0), (-1, -1), 0.25, colors.grey),
        ],
    )

    elements.append(summary_tbl)
    elements.append(Spacer(1, 1 * cm))

    # ───────────────────── 2) TABELLA VALIDAZIONE ────────────────────
    elements.append(Paragraph("Dettaglio verifiche", styles["Heading2"]))
    elements.append(Spacer(1, 0.2 * cm))

    check_rows = [["Verifica", "Esito"]]
    for check, ok in validation_result.validations.items():
        pretty = "Num. pagina (footer)" if check == "page_numbers_position" else check.replace("_", " ").capitalize()
        sign   = "✓" if ok else "✗"
        color  = GREEN if ok else RED

        esito  = Paragraph(
            f"<font color='{hex_(color)}'>{sign}</font>",
            styles["Normal"],
        )
        check_rows.append([pretty, esito])      # ← usa Paragraph

    val_table = Table(
        check_rows,
        colWidths=[10 * cm, 2 * cm],
        hAlign="LEFT",
        style=[
            ("BACKGROUND", (0, 0), (-1, 0), BG_HEAD),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("BOX", (0, 0), (-1, -1), 0.25, colors.grey),
        ],
    )
    elements.append(val_table)

    elements.append(Spacer(1, 0.8 * cm))
    elements.append(HRFlowable(width="100%", color=colors.grey))
    elements.append(Spacer(1, 0.8 * cm))

    # ───────────────────── 3) DISTRIBUZIONE FONT ───────────────────
    if report_format.include_charts and validation_result.detailed_analysis:
        da = validation_result.detailed_analysis
        if da.fonts:
            elements.append(Paragraph("Distribuzione font", styles["Heading2"]))
            elements.append(Spacer(1, 0.2 * cm))

            # intestazione
            font_rows = [["Font", "Size pt → occorrenze", "Totale"]]

            # ordina i font per utilizzo discendente
            for name, info in sorted(
                da.fonts.items(), key=lambda it: it[1].count, reverse=True
            ):
                # ordina le singole dimensioni per occorrenze discendenti e vai a capo
                size_parts = sorted(
                    info.size_counts.items(), key=lambda p: p[1], reverse=True
                )
                size_lines = "<br/>".join(f"{s} → {c}" for s, c in size_parts)

                # usa Paragraph per supportare <br/>
                size_para = Paragraph(size_lines, styles["Small"])
                font_rows.append([name, size_para, str(info.count)])

            font_tbl = Table(
                font_rows,
                colWidths=[5 * cm, 7 * cm, 3 * cm],
                style=[
                    ("BACKGROUND", (0, 0), (-1, 0), BG_HEAD),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("BOX", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_HEAD]),
                    ("VALIGN", (0, 1), (-1, -1), "TOP"),
                ],
            )
            elements.append(font_tbl)
            elements.append(Spacer(1, 0.5 * cm))

    # ───────────────────── 4) RACCOMANDAZIONI  ────────────────────
    if report_format.include_recommendations and not validation_result.is_valid:
        elements.append(Paragraph("Raccomandazioni", styles["Heading2"]))
        elements.append(Spacer(1, 0.2 * cm))

        bullets = []
        if not validation_result.validations["page_size"]:
            bullets.append(
                f"Adeguare la dimensione pagina a "
                f"{spec.page_width_cm} × {spec.page_height_cm} cm."
            )
        if not validation_result.validations["margins"]:
            bullets.append(
                "Verificare i margini per rispettare i valori specificati."
            )
        if not validation_result.validations["has_toc"] and spec.requires_toc:
            bullets.append("Inserire un indice automatico (TOC).")

        for b in bullets:
            elements.append(Paragraph("• " + b, styles["Normal"]))
            elements.append(Spacer(1, 0.1 * cm))

    # ───────────────────── 5) JSON GREZZO (opzionale) ────────────────
    if report_format.include_detailed_analysis and validation_result.raw_props:
        elements.append(PageBreak())
        elements.append(Paragraph("Raw extract (debug)", styles["Heading2"]))
        elements.append(Spacer(1, 0.2 * cm))

        raw_json = json.dumps(validation_result.raw_props, indent=2, ensure_ascii=False)
        mono = ParagraphStyle(
            "Mono",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=7,
            leading=8,
        )
        for line in raw_json.split("\n")[:800]:  # mostra massimo ~800 righe
            elements.append(Paragraph(line.replace(" ", "&nbsp;"), mono))

    # ───────────────────── COSTRUISCI PDF ──────────────────────────────
    doc.build(elements)
    buff.seek(0)
    return buff.read()


def send_ticket_to_zendesk(
    subject: str,
    body: str,
    pdf_bytes: bytes,
    pdf_name: str,
    requester_email: str,
):
    """
    • carica l’allegato (uploads.json)  → upload_token
    • crea il ticket (tickets.json)     → id ticket

    Il requester viene impostato all’e-mail del cliente; l’agente API rimane assegnato
    ma il cliente riceverà la notifica come vero mittente.
    """
    s = settings  # abbreviazione

    auth = (f"{s.ZENDESK_EMAIL}/token", s.ZENDESK_API_TOKEN)
    base = f"https://{s.ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"

    # ---- 1) carica allegato ---------------------------------
    up_res = requests.post(
        f"{base}/uploads.json?filename={pdf_name}",
        auth=auth,
        files={"file": (pdf_name, pdf_bytes, "application/pdf")},
    )
    up_res.raise_for_status()
    upload_token = up_res.json()["upload"]["token"]

    # ---- 2) crea ticket -------------------------------------
    ticket_data = {
        "ticket": {
            "subject": subject,
            # IMPOSTA del richiedente esterno
            "requester": {"name": requester_email.split("@")[0], "email": requester_email},
            "comment": {
                "body": body,
                "uploads": [upload_token],
                "public": True,
            },
            # opzionale: metti l’agente come assegnatario
            # "assignee_email": s.ZENDESK_EMAIL,
        }
    }

    tk_res = requests.post(
        f"{base}/tickets.json",
        auth=auth,
        json=ticket_data,
    )
    tk_res.raise_for_status()
    return tk_res.json()["ticket"]["id"]


# ─── API routes ──────────────────────────────────────────────────

from api import api_router  # oggetto APIRouter definito in api.py

app.include_router(cast(APIRouter, api_router))        # mypy sa che è un APIRouter

# =====  FILE STATICI & FRONTEND  =====
import pathlib

if getattr(sys, 'frozen', False):
    BASE_DIR = pathlib.Path(sys._MEIPASS)  # cartella temporanea del bundle
else:
    BASE_DIR = pathlib.Path(__file__).parent
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

# reindirizza '/' → GUI
@app.get("/", include_in_schema=False)
async def frontend():
    return RedirectResponse(url="/static/index.html")
# =====================================

# Configurazione CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Aggiungi compressione GZip per le prestazioni
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Aggiungi middleware host fidati per la sicurezza
if os.environ.get("ENVIRONMENT") == "production":
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["*"]  # Configura con il tuo dominio reale in produzione
    )

# Gestore eccezioni per eccezioni non catturate
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Global exception handler for uncaught exceptions"""
    log.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."}
    )
