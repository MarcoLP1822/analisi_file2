# Importazioni librerie standard
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pdfplumber

# Librerie per elaborazione documenti
import PyPDF2
import requests
from docx import Document as DocxDocument
from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from odf.opendocument import load as load_odt
from odf.style import PageLayoutProperties

# Importazioni librerie di terze parti
from odf.text import H as OdtHeading
from passlib.context import CryptContext
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table

# Importazioni locali
from config import Settings
from models import (
    DetailedDocumentAnalysis,
    DocumentSpec,
    FontInfo,
    ImageInfo,
    ReportFormat,
    ValidationResult,
)

# Inizializzazione delle impostazioni
settings = Settings()

# Configurazione logging
logger = logging.getLogger("document_validator")

# Configurazione sicurezza
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
ACCESS_TOKEN_EXPIRE_DELTA = settings.access_token_expires

# Configurazione CORS (origini)
origins = settings.allowed_origins_list

# Carica variabili d'ambiente e configura percorsi
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configura logging basato sull'ambiente
log_level = getattr(logging, settings.LOG_LEVEL)

# percorso file log preso da variabile d'ambiente.
# Vuoto o "-"  => solo console (stdout).
LOG_PATH = os.getenv("LOG_PATH", "").strip()

handlers = [logging.StreamHandler(sys.stdout)]

if LOG_PATH and LOG_PATH != "-":
    log_file = Path(LOG_PATH)
    log_file.parent.mkdir(parents=True, exist_ok=True)  # crea la cartella se non esiste
    handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=handlers,
)
logger = logging.getLogger("document_validator")

# Configurazione di sicurezza
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Crea l'app principale senza prefisso
app = FastAPI(
    title="Document Validator API",
    description="API for validating and analyzing documents against specifications",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Funzioni di autenticazione e sicurezza
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def extract_docx_properties(file_content: bytes) -> dict[str, Any]:
    """Estrae proprietà da file DOCX"""
    doc = DocxDocument(io.BytesIO(file_content))
    # --- ESTRAZIONE HEADER ---
    headers = []
    for section in doc.sections:
        header = section.header
        if header:
            text = "\n".join([p.text for p in header.paragraphs if p.text.strip()])
            if text:
                headers.append(text)
    
    # --- ESTRAZIONE FOOTNOTES ---
    footnotes_texts = []
    footnotes_part = None
    try:
        footnotes_part = doc.part.footnotes_part
    except AttributeError:
        footnotes_part = None
    
    if footnotes_part:
        for footnote in footnotes_part.footnotes:
            texts = []
            for p in footnote.paragraphs:
                if p.text.strip():
                    texts.append(p.text)
            if texts:
                footnotes_texts.append("\n".join(texts))

    # Verifica TUTTE le sezioni per inconsistenze di formato
    section_data = []
    inconsistent_sections = []
    
    for i, section in enumerate(doc.sections):
        width_cm = section.page_width / 360000
        height_cm = section.page_height / 360000
        
        section_info = {
            'section_num': i + 1,
            'width_cm': width_cm,
            'height_cm': height_cm,
            'margins': {
                'top_cm': section.top_margin / 360000,
                'bottom_cm': section.bottom_margin / 360000,
                'left_cm': section.left_margin / 360000,
                'right_cm': section.right_margin / 360000
            }
        }
        section_data.append(section_info)
    
    # Usa la prima sezione come riferimento
    first_section = section_data[0]
    page_width_cm = first_section['width_cm']
    page_height_cm = first_section['height_cm']
    margins = first_section['margins']
    
    # Controlla inconsistenze tra sezioni (tolleranza di 0.1 cm)
    for section_info in section_data[1:]:
        if (abs(section_info['width_cm'] - page_width_cm) > 0.1 or 
            abs(section_info['height_cm'] - page_height_cm) > 0.1):
            inconsistent_sections.append({
                'section': section_info['section_num'],
                'size': f"{section_info['width_cm']:.1f}x{section_info['height_cm']:.1f}cm"
            })
    
    # Controlla intestazioni (potenziale indice)
    headings = []
    for paragraph in doc.paragraphs:
        if paragraph.style.name.startswith('Heading'):
            headings.append(paragraph.text)
    
    has_toc = len(headings) > 0
    
    # Estrae analisi dettagliata
    detailed_analysis = extract_docx_detailed_analysis(doc)
    
    return {
        'page_size': {'width_cm': page_width_cm, 'height_cm': page_height_cm},
        'margins': margins,
        'has_toc': has_toc,
        'headings': headings,
        'headers': headers,
        'footnotes': footnotes_texts,
        'detailed_analysis': detailed_analysis,
        # Nuove informazioni per il controllo completo
        'all_section_data': section_data,
        'inconsistent_sections': inconsistent_sections,
        'has_size_inconsistencies': len(inconsistent_sections) > 0
    }


def extract_docx_detailed_analysis(doc: DocxDocument) -> DetailedDocumentAnalysis:
    """
    Analisi DOCX: ora conta le occorrenze per ciascuna coppia font+size.
    """
    fonts: dict[str, FontInfo] = {}
    paragraph_count = 0
    line_spacing: dict[str, float] = {}
    toc_structure: list[dict[str, str]] = []
    has_color_text = False
    colored_elements_count = 0

    # fallback: font e dimensione di default dallo stile "Normal"
    default_font_name = doc.styles["Normal"].font.name or "Default"
    default_font_size = (
        doc.styles["Normal"].font.size.pt
        if doc.styles["Normal"].font.size
        else 11.0
    )

    for paragraph in doc.paragraphs:
        paragraph_count += 1

        # interlinea media per stile
        if paragraph._element.pPr is not None and paragraph._element.pPr.spacing is not None:
            if paragraph._element.pPr.spacing.line is not None:
                style_name = paragraph.style.name
                spacing_value = paragraph._element.pPr.spacing.line / 240
                line_spacing[style_name] = (
                    spacing_value
                    if style_name not in line_spacing
                    else (line_spacing[style_name] + spacing_value) / 2
                )

        # struttura TOC
        if paragraph.style.name.startswith("Heading"):
            lev = (
                int(paragraph.style.name.replace("Heading", ""))
                if paragraph.style.name != "Heading"
                else 1
            )
            toc_structure.append({"level": str(lev), "text": paragraph.text})

        # ---------- scan run ----------
        for run in paragraph.runs:
            # nome font (run -> paragrafo -> Normal)
            font_name = (
                run.font.name
                or paragraph.style.font.name
                or default_font_name
            )

            # dimensione font in pt
            if run.font.size:
                font_size = round(run.font.size.pt, 1)
            elif paragraph.style.font.size:
                font_size = round(paragraph.style.font.size.pt, 1)
            else:
                font_size = round(default_font_size, 1)

            # colore?
            if run.font.color and run.font.color.rgb and run.font.color.rgb != "000000":
                has_color_text = True
                colored_elements_count += 1

            # aggiorna dizionario caratteri
            fi = fonts.get(font_name)
            if not fi:
                fi = FontInfo(sizes=[font_size], count=0, size_counts={})
                fonts[font_name] = fi

            fi.count += 1
            if font_size not in fi.sizes:
                fi.sizes.append(font_size)
            fi.size_counts[font_size] = fi.size_counts.get(font_size, 0) + 1

    # immagini
    image_count = 0
    total_image_size = 0
    has_color_pages = False
    for rel in doc.part.rels.values():
        if rel.target_ref.startswith("media/"):
            image_count += 1
            if hasattr(rel.target_part, "blob"):
                total_image_size += len(rel.target_part.blob)
            has_color_pages = True
            colored_elements_count += 1

    image_info = None
    if image_count:
        image_info = ImageInfo(
            count=image_count,
            avg_size_kb=round((total_image_size / image_count) / 1024, 2),
        )

    # metadati
    metadata = {}
    cp = doc.core_properties
    if cp:
        if cp.author: metadata["author"] = cp.author
        if cp.title:  metadata["title"]  = cp.title
        if cp.created:  metadata["created"]  = cp.created.isoformat()
        if cp.modified: metadata["modified"] = cp.modified.isoformat()

    return DetailedDocumentAnalysis(
        fonts=fonts,
        images=image_info,
        line_spacing=line_spacing,
        paragraph_count=paragraph_count,
        toc_structure=toc_structure,
        metadata=metadata,
        has_color_pages=has_color_pages,
        has_color_text=has_color_text,
        colored_elements_count=colored_elements_count,
    )


def extract_odt_properties(file_content: bytes) -> dict[str, Any]:
    """Extract properties from ODT file"""
    doc = load_odt(io.BytesIO(file_content))

    # Estraggo headers e footers (footnotes)
    headers = []
    footnotes = []

    # Ottiene le proprietà del layout di pagina
    page_layouts = doc.getElementsByType(PageLayoutProperties)
    
    if not page_layouts:
        return {
            'page_size': {'width_cm': 0, 'height_cm': 0},
            'margins': {'top_cm': 0, 'bottom_cm': 0, 'left_cm': 0, 'right_cm': 0},
            'has_toc': False,
            'headings': [],
            'detailed_analysis': DetailedDocumentAnalysis()
        }
    
    # Ottiene il layout della prima pagina
    page_layout = page_layouts[0]
    
    # Analizza le dimensioni
    # ODT memorizza i valori con unità, come '21cm'
    def parse_dimension(value: str) -> float:
        if not value:
            return 0
        
        # Rimuove unità e converte a float
        if 'cm' in value:
            return float(value.replace('cm', ''))
        elif 'mm' in value:
            return float(value.replace('mm', '')) / 10  # Converte mm in cm
        elif 'in' in value:
            return float(value.replace('in', '')) * 2.54  # Converte pollici in cm
        
        return float(value)
    
    page_width = parse_dimension(page_layout.getAttribute('fo:page-width'))
    page_height = parse_dimension(page_layout.getAttribute('fo:page-height'))
    
    margin_top = parse_dimension(page_layout.getAttribute('fo:margin-top'))
    margin_bottom = parse_dimension(page_layout.getAttribute('fo:margin-bottom'))
    margin_left = parse_dimension(page_layout.getAttribute('fo:margin-left'))
    margin_right = parse_dimension(page_layout.getAttribute('fo:margin-right'))
    
    # Estrae intestazioni
    headings = []
    for heading in doc.getElementsByType(OdtHeading):
        if heading.firstChild:
            headings.append(heading.firstChild.data)
    
    has_toc = len(headings) > 0
    
    # Controlla immagini ed elementi colorati
    from odf.draw import Image as OdtImage
    from odf.style import GraphicProperties, TextProperties
    
    image_count = len(doc.getElementsByType(OdtImage))
    has_color_pages = image_count > 0  # Assume che le immagini abbiano colori
    has_color_text = False
    colored_elements_count = image_count
    
    # Controlla testo colorato
    text_props = doc.getElementsByType(TextProperties)
    for prop in text_props:
        color = prop.getAttribute('fo:color')
        if color and color != '#000000':
            has_color_text = True
            colored_elements_count += 1
    
    # Controlla grafica colorata
    graphic_props = doc.getElementsByType(GraphicProperties)
    for prop in graphic_props:
        fill_color = prop.getAttribute('draw:fill-color')
        if fill_color and fill_color != '#000000':
            has_color_pages = True
            colored_elements_count += 1
    
    # Crea un'analisi dettagliata per ODT
    detailed_analysis = DetailedDocumentAnalysis(
        fonts={"Default": FontInfo(sizes=[11.0], count=1)},
        paragraph_count=len(doc.getElementsByType(OdtHeading)),
        toc_structure=[{"level": str(h.getAttribute('text:outline-level') or '1'), "text": h.firstChild.data} 
                      for h in doc.getElementsByType(OdtHeading) if h.firstChild],
        metadata={},
        has_color_pages=has_color_pages,
        has_color_text=has_color_text,
        colored_elements_count=colored_elements_count,
        images=ImageInfo(count=image_count, avg_size_kb=10.0) if image_count > 0 else None
    )
    
    return {
        'page_size': {'width_cm': page_width, 'height_cm': page_height},
        'margins': {
            'top_cm': margin_top,
            'bottom_cm': margin_bottom,
            'left_cm': margin_left,
            'right_cm': margin_right
        },
        'has_toc': has_toc,
        'headings': headings,
        'headers': headers,
        'footnotes': footnotes,
        'detailed_analysis': detailed_analysis
    }

def extract_pdf_properties(file_content: bytes) -> dict[str, Any]:
    """
    Estrae le proprietà di un PDF usando la TrimBox.
    • Verifica coerenza formato (TrimBox) fra le pagine
    • Calcola i margini (TrimBox vs MediaBox)
    • Rileva la posizione del numero pagina (bottom-center / bottom-left / bottom-right)
    """
    import io

    CM_PER_PT = 0.0352778

    pdf_io = io.BytesIO(file_content)
    pdf_reader = PyPDF2.PdfReader(pdf_io)
    if len(pdf_reader.pages) == 0:
        raise HTTPException(status_code=400, detail="PDF file has no pages")

    # ---------- helper -------------------------------------------------
    def pick_box(page: PyPDF2._page.PageObject):
        """Restituisce TrimBox, altrimenti CropBox, altrimenti MediaBox."""
        for attr in ("trimbox", "cropbox", "mediabox"):
            box = getattr(page, attr, None)
            if box is not None:
                return box
        return page.mediabox  # extrema-ratio

    # ---------- formato pagina & coerenza ------------------------------
    page_boxes, inconsistent_pages = [], []
    for idx, pg in enumerate(pdf_reader.pages):
        box = pick_box(pg)
        w_pt, h_pt = float(box.width), float(box.height)
        page_boxes.append(
            {"page": idx + 1, "width_cm": w_pt*CM_PER_PT, "height_cm": h_pt*CM_PER_PT}
        )

    ref_w, ref_h = page_boxes[0]["width_cm"], page_boxes[0]["height_cm"]
    for pb in page_boxes[1:]:
        if abs(pb["width_cm"]-ref_w) > .1 or abs(pb["height_cm"]-ref_h) > .1:
            inconsistent_pages.append(pb)

    # ---------- margini (TrimBox vs MediaBox) --------------------------
    first_pg = pdf_reader.pages[0]
    trim, media = pick_box(first_pg), first_pg.mediabox
    margins = {
        "top_cm":    (float(media.upper_right[1]) - float(trim.upper_right[1])) * CM_PER_PT,
        "bottom_cm": (float(trim.lower_left[1])  - float(media.lower_left[1])) * CM_PER_PT,
        "left_cm":   (float(trim.lower_left[0])  - float(media.lower_left[0])) * CM_PER_PT,
        "right_cm":  (float(media.upper_right[0]) - float(trim.upper_right[0])) * CM_PER_PT,
    }

    # ---------- heading / TOC euristico + numero pagina ----------------
    headings, headers, footnotes = [], [], []
    page_num_positions = []  # ‘center’, ‘left’, ‘right’, ‘missing’

    with pdfplumber.open(pdf_io) as pdf:
        h_pt = pdf.pages[0].height
        w_pt = pdf.pages[0].width
        bottom_th = 56              # ~2 cm

        for idx, p in enumerate(pdf.pages):
            txt = (p.extract_text() or "").lower()
            if any(k in txt for k in ("indice", "table of contents", "contents", "toc", "sommario")):
                headings.append("TOC detected")

            # header/footer veloci (prime 3 pagine)
            if idx < 3 and txt:
                lines = txt.splitlines()
                headers.append(lines[0].strip())
                footnotes.append(lines[-1].strip())

            # ---- rileva numero pagina --------------------------------
            pos = "mancante"
            for w in p.extract_words(keep_blank_chars=False, use_text_flow=True):
                if w["text"].strip().isdigit() and int(w["text"]) == idx+1:
                    if w["bottom"] < h_pt - bottom_th:   # non in footer
                        continue
                    cx = (w["x0"] + w["x1"]) / 2
                    if abs(cx - w_pt/2) <= w_pt*0.15:
                        pos = "centro"
                    elif cx < w_pt*0.25:
                        pos = "sinistra"
                    elif cx > w_pt*0.75:
                        pos = "destra"
                    break
            page_num_positions.append(pos)

    # ---------- analisi dettagliata -----------------------------------
    detailed_analysis = extract_pdf_detailed_analysis(file_content)

    return {
        "page_size": {"width_cm": ref_w, "height_cm": ref_h},
        "margins": margins,
        "has_toc": bool(headings),
        "headings": headings,
        "headers": headers,
        "footnotes": footnotes,
        "detailed_analysis": detailed_analysis,
        "page_count": len(pdf_reader.pages),
        # nuovi campi ↓
        "page_num_positions": page_num_positions,
        "inconsistent_pages": inconsistent_pages,
        "has_size_inconsistencies": bool(inconsistent_pages),
    }


def extract_pdf_detailed_analysis(file_content: bytes) -> DetailedDocumentAnalysis:
    """
    Analisi PDF:
    • raccoglie font, paragrafi, TOC, metadati
    • rileva immagini e testo colorato
    • calcola il numero di *pagine* che contengono elementi a colori
      (colored_elements_count diventa pages_with_color)
    """
    import io


    pdf_io = io.BytesIO(file_content)
    pdf_doc = fitz.open(stream=pdf_io, filetype="pdf")

    fonts: dict[str, FontInfo] = {}
    toc_structure: list[dict[str, str]] = []
    paragraph_count = 0
    image_count = 0
    total_image_size = 0

    color_pages: set[int] = set()
    has_color_text = False

    # -------- metadati ------------------------------------------------
    metadata = {k: str(v) for k, v in pdf_doc.metadata.items() if v and k not in ("format", "encryption")}

    # -------- scorre pagine ------------------------------------------
    for page_num, page in enumerate(pdf_doc):
        # paragrafi approssimati
        paragraph_count += len(page.get_text("blocks"))

        page_is_color = False  # flag locale

        # immagini
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                base_image = pdf_doc.extract_image(xref)
                if base_image:
                    image_count += 1
                    total_image_size += len(base_image["image"])
                    page_is_color = True
            except Exception:
                pass

        # pixel color check (mini-campionamento)
        if not page_is_color:
            pix = page.get_pixmap(samples=8, colorspace=fitz.csRGB)
            for px in pix.samples:
                r, g, b = px[0], px[1], px[2]
                if r != g or g != b:  # non scala di grigi
                    page_is_color = True
                    break

        # font & testo colorato
        for span in page.get_text("dict")["blocks"]:
            for l in span.get("lines", []):
                for s in l.get("spans", []):
                    font_name = s["font"]
                    font_size = round(float(s["size"]), 1)

                    # aggiorna font dict
                    fi = fonts.setdefault(font_name, FontInfo(sizes=[], count=0, size_counts={}))
                    fi.count += 1
                    if font_size not in fi.sizes:
                        fi.sizes.append(font_size)
                    fi.size_counts[font_size] = fi.size_counts.get(font_size, 0) + 1

                    # colore RGB
                    if s["color"] not in (0, 0x000000):
                        has_color_text = True
                        page_is_color = True

        if page_is_color:
            color_pages.add(page_num)

    # -------- TOC -----------------------------------------------------
    toc = pdf_doc.get_toc()
    if toc:
        for level, title, _ in toc:
            toc_structure.append({"level": str(level), "text": title})

    # -------- immagini info ------------------------------------------
    image_info = None
    if image_count:
        image_info = ImageInfo(
            count=image_count,
            avg_size_kb=round((total_image_size / image_count) / 1024, 2),
        )

    return DetailedDocumentAnalysis(
        fonts=fonts,
        images=image_info,
        line_spacing={"Default": 1.2},
        paragraph_count=paragraph_count,
        toc_structure=toc_structure,
        metadata=metadata,
        has_color_pages=bool(color_pages),
        has_color_text=has_color_text,
        colored_elements_count=len(color_pages),  # = pagine con colore
    )

# ──────────────────────────────────────────────────────────────────
#  GENERATE PDF – versione “client-friendly”
# ──────────────────────────────────────────────────────────────────
def generate_validation_report(
    validation_result: ValidationResult,
    spec: DocumentSpec,
    report_format: ReportFormat,
) -> bytes:
    import datetime
    import io
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


from api import api_router as api_routes

app.include_router(api_routes)

# =====  FILE STATICI & FRONTEND  =====
import pathlib
import sys

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

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Gestore eccezioni per eccezioni non catturate
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Global exception handler for uncaught exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."}
    )
