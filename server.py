# Standard library imports
import io
import json
import logging
import os
import sys
import tempfile
import requests, base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Union

# Third-party imports
from odf.text import H as OdtHeading
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Inches, Cm
from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Response,
    Depends,
    status,
    Request
)
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from odf.opendocument import load as load_odt
from odf.style import PageLayoutProperties
from odf.text import H as OdtHeading
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image
)

# Local imports
from config import Settings
from utils.conversion import convert_to_pdf_via_lo, extract_pdf_page_count
from utils.order_parser import parse_order
from models import (
    TokenData,
    FontInfo,
    ImageInfo,
    DetailedDocumentAnalysis,
    DocumentSpec,
    DocumentSpecCreate,
    ValidationResult,
    EmailTemplate,
    EmailTemplateCreate,
    ReportFormat
)

# Document processing libraries
import PyPDF2
import pdfplumber
import fitz  # PyMuPDF
from pdfminer.high_level import extract_text

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
origins = settings.ALLOWED_ORIGINS

# Load environment variables and configure paths
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging based on environment
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

# Security configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Create the main app without a prefix
app = FastAPI(
    title="Document Validator API",
    description="API for validating and analyzing documents against specifications",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Authentication and security functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def extract_docx_properties(file_content: bytes) -> Dict[str, Any]:
    """Extract properties from DOCX file"""
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

    section = doc.sections[0]
    # Convert from EMU (English Metric Units) to cm (1 cm = 360000 EMU)
    page_width_cm = section.page_width / 360000
    page_height_cm = section.page_height / 360000
    
    margins = {
        'top_cm': section.top_margin / 360000,
        'bottom_cm': section.bottom_margin / 360000,
        'left_cm': section.left_margin / 360000,
        'right_cm': section.right_margin / 360000
    }
    
    # Check for headings (potential TOC)
    headings = []
    for paragraph in doc.paragraphs:
        if paragraph.style.name.startswith('Heading'):
            headings.append(paragraph.text)
    
    has_toc = len(headings) > 0
    
    # Extract detailed analysis
    detailed_analysis = extract_docx_detailed_analysis(doc)
    
    return {
        'page_size': {'width_cm': page_width_cm, 'height_cm': page_height_cm},
        'margins': margins,
        'has_toc': has_toc,
        'headings': headings,
        'headers': headers,
        'footnotes': footnotes_texts,
        'detailed_analysis': detailed_analysis
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

    # fallback: font e size di default dallo stile "Normal"
    default_font_name = doc.styles["Normal"].font.name or "Default"
    default_font_size = (
        doc.styles["Normal"].font.size.pt
        if doc.styles["Normal"].font.size
        else 11.0
    )

    for paragraph in doc.paragraphs:
        paragraph_count += 1

        # line spacing medio per stile
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
            # font name (run -> paragrafo -> Normal)
            font_name = (
                run.font.name
                or paragraph.style.font.name
                or default_font_name
            )

            # font size in pt
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

            # aggiorna dizionario font
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


def extract_odt_properties(file_content: bytes) -> Dict[str, Any]:
    """Extract properties from ODT file"""
    doc = load_odt(io.BytesIO(file_content))

    # Estraggo headers e footers (footnotes)
    headers = []
    footnotes = []

    # Get page layout properties
    page_layouts = doc.getElementsByType(PageLayoutProperties)
    
    if not page_layouts:
        return {
            'page_size': {'width_cm': 0, 'height_cm': 0},
            'margins': {'top_cm': 0, 'bottom_cm': 0, 'left_cm': 0, 'right_cm': 0},
            'has_toc': False,
            'headings': [],
            'detailed_analysis': DetailedDocumentAnalysis()
        }
    
    # Get first page layout
    page_layout = page_layouts[0]
    
    # Parse dimensions
    # ODT stores values with units, like '21cm'
    def parse_dimension(value: str) -> float:
        if not value:
            return 0
        
        # Remove units and convert to float
        if 'cm' in value:
            return float(value.replace('cm', ''))
        elif 'mm' in value:
            return float(value.replace('mm', '')) / 10  # Convert mm to cm
        elif 'in' in value:
            return float(value.replace('in', '')) * 2.54  # Convert inches to cm
        
        return float(value)
    
    page_width = parse_dimension(page_layout.getAttribute('fo:page-width'))
    page_height = parse_dimension(page_layout.getAttribute('fo:page-height'))
    
    margin_top = parse_dimension(page_layout.getAttribute('fo:margin-top'))
    margin_bottom = parse_dimension(page_layout.getAttribute('fo:margin-bottom'))
    margin_left = parse_dimension(page_layout.getAttribute('fo:margin-left'))
    margin_right = parse_dimension(page_layout.getAttribute('fo:margin-right'))
    
    # Extract headings
    headings = []
    for heading in doc.getElementsByType(OdtHeading):
        if heading.firstChild:
            headings.append(heading.firstChild.data)
    
    has_toc = len(headings) > 0
    
    # Check for images and color elements
    from odf.draw import Image as OdtImage
    from odf.style import TextProperties, GraphicProperties
    
    image_count = len(doc.getElementsByType(OdtImage))
    has_color_pages = image_count > 0  # Assume images have color
    has_color_text = False
    colored_elements_count = image_count
    
    # Check for colored text
    text_props = doc.getElementsByType(TextProperties)
    for prop in text_props:
        color = prop.getAttribute('fo:color')
        if color and color != '#000000':
            has_color_text = True
            colored_elements_count += 1
    
    # Check for colored graphics
    graphic_props = doc.getElementsByType(GraphicProperties)
    for prop in graphic_props:
        fill_color = prop.getAttribute('draw:fill-color')
        if fill_color and fill_color != '#000000':
            has_color_pages = True
            colored_elements_count += 1
    
    # Create a detailed analysis for ODT
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

def extract_pdf_properties(file_content: bytes) -> Dict[str, Any]:
    """Extract properties from PDF file"""
    pdf_bytes_io = io.BytesIO(file_content)
    
    # Extract basic page properties with PyPDF2
    pdf_reader = PyPDF2.PdfReader(pdf_bytes_io)
    page_count = len(pdf_reader.pages)

    if len(pdf_reader.pages) == 0:
        raise HTTPException(status_code=400, detail="PDF file has no pages")
    
    # Get page size
    first_page = pdf_reader.pages[0]
    page_width_points = float(first_page.mediabox.width)
    page_height_points = float(first_page.mediabox.height)
    
    # Convert points to cm (1 point = 0.0352778 cm)
    page_width_cm = page_width_points * 0.0352778
    page_height_cm = page_height_points * 0.0352778
    
    # Get margins and headings using pdfplumber
    headings = []
    has_toc = False
    
    with pdfplumber.open(pdf_bytes_io) as pdf:
        # Process only first few pages for performance
        pages_to_check = min(3, len(pdf.pages))
        
        # ---------- calcolo margini pagina ----------
        # PDF coordinate origin: (0,0) in basso-sinistra

        # a) dimensioni carta (MediaBox)
        media_w_pt = page_width_points
        media_h_pt = page_height_points

        # b) dimensioni area ritagliata (CropBox se presente, altrimenti MediaBox)
        try:
            # PyPDF2 restituisce CoordinateObject; cast a float
            crop_left   = float(first_page.cropbox.lower_left[0])
            crop_bottom = float(first_page.cropbox.lower_left[1])
            crop_right  = float(first_page.cropbox.upper_right[0])
            crop_top    = float(first_page.cropbox.upper_right[1])
        except Exception:
            # CropBox mancante → usa MediaBox (zero margini)
            crop_left = crop_bottom = 0.0
            crop_right  = media_w_pt
            crop_top    = media_h_pt

        # Margini in punti
        left_margin_points   = crop_left
        bottom_margin_points = crop_bottom
        right_margin_points  = media_w_pt - crop_right
        top_margin_points    = media_h_pt - crop_top

        # Conversione in cm (1 pt = 0.0352778 cm)
        left_margin_cm   = left_margin_points   * 0.0352778
        bottom_margin_cm = bottom_margin_points * 0.0352778
        right_margin_cm  = right_margin_points  * 0.0352778
        top_margin_cm    = top_margin_points    * 0.0352778
            
        # Check for headings and table of contents
        for i in range(pages_to_check):
            page = pdf.pages[i]
            text = page.extract_text()
            
            if text:
                lines = text.split('\n')
                
                # Look for potential headings (numbered sections or large text)
                for line in lines:
                    # Simple heuristic: check for numbered sections (e.g., "1. Introduction", "2.1 Methods")
                    if any(line.strip().startswith(f"{i}.") for i in range(1, 10)) or len(line.strip()) < 60:
                        headings.append(line.strip())
                        
                # Look for "Table of Contents", "Contents", "Index" keywords
                if any(keyword in text for keyword in ["Table of Contents", "Contents", "Index", "TOC"]):
                    has_toc = True
        
        # Ensure we have at least some dummy headings data if none detected
        if not headings and has_toc:
            headings = ["[PDF contains a Table of Contents]"]
    
    # Extract detailed analysis
    detailed_analysis = extract_pdf_detailed_analysis(file_content)

    headers = []
    footnotes = []
    
    with pdfplumber.open(pdf_bytes_io) as pdf:
        for page in pdf.pages[:3]:  # analizza prime 3 pagine per esempio
            text = page.extract_text()
            if not text:
                continue
            lines = text.split('\n')
            if len(lines) > 2:
                headers.append(lines[0].strip())
                footnotes.append(lines[-1].strip())

    return {
        'page_size': {'width_cm': page_width_cm, 'height_cm': page_height_cm},
        'margins': {
            'top_cm': top_margin_cm,
            'bottom_cm': bottom_margin_cm,
            'left_cm': left_margin_cm,
            'right_cm': right_margin_cm
        },
        'has_toc': has_toc or len(headings) > 0,
        'headings': headings,
        'headers': headers,   
        'footnotes': footnotes,
        'detailed_analysis': detailed_analysis,
        'page_count': page_count,
    }


def extract_pdf_detailed_analysis(file_content: bytes) -> DetailedDocumentAnalysis:
    """Extract detailed analysis from PDF file"""
    pdf_bytes_io = io.BytesIO(file_content)
    pdf_doc = fitz.open(stream=pdf_bytes_io, filetype="pdf")
    
    # Font analysis
    fonts = {}
    paragraph_count = 0
    toc_structure = []
    image_count = 0
    total_image_size = 0
    has_color_pages = False
    has_color_text = False
    colored_elements_count = 0
    
    # Extract metadata
    metadata = {}
    if pdf_doc.metadata:
        for key, value in pdf_doc.metadata.items():
            if value and key not in ['format', 'encryption']:
                metadata[key] = str(value)
    
    # Process each page
    for page_num, page in enumerate(pdf_doc):
        # Count paragraphs (approximate based on blocks)
        blocks = page.get_text("blocks")
        paragraph_count += len(blocks)
        
        # Check if page has color
        pixmap = page.get_pixmap()
        if pixmap.colorspace and pixmap.colorspace != fitz.csGRAY:
            # Sample some pixels to check for non-grayscale colors
            for i in range(0, pixmap.width, pixmap.width // 10):
                for j in range(0, pixmap.height, pixmap.height // 10):
                    pixel = pixmap.pixel(i, j)
                    # Check if RGB values differ (indicating color)
                    if len(pixel) >= 3 and not (pixel[0] == pixel[1] == pixel[2]):
                        has_color_pages = True
                        colored_elements_count += 1
                        break
                if has_color_pages:
                    break
        
        # Extract images
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            image_count += 1
            try:
                xref = img[0]
                base_image = pdf_doc.extract_image(xref)
                if base_image:
                    total_image_size += len(base_image["image"])
                    # Assuming images might have color
                    has_color_pages = True
                    colored_elements_count += 1
            except:
                pass
        
        # Extract fonts and check for potential colored text
        for font in page.get_fonts():
            font_name = font[3]
            font_size = font[1]
            
            # Check if font_size is a string and convert to float if needed
            if isinstance(font_size, str):
                try:
                    font_size = float(font_size)
                except ValueError:
                    font_size = 12.0  # Default font size if conversion fails
            
            # Extract text colors (this is approximate in PDF)
            text_instances = page.search_for(font_name[:10] if len(font_name) > 10 else font_name)
            for inst in text_instances:
                # Try to get color info from text spans
                spans = page.get_textpage().extract_spans()
                for span in spans:
                    if span["color"] and span["color"] != 0:  # Non-black color
                        has_color_text = True
                        colored_elements_count += 1
                        break
            
            if font_name in fonts:
                fonts[font_name].count += 1
                if font_size not in fonts[font_name].sizes:
                    fonts[font_name].sizes.append(round(font_size, 1))
            else:
                fonts[font_name] = FontInfo(
                    sizes=[round(font_size, 1)],
                    count=1
                )
    
    # Get document outline/TOC
    toc = pdf_doc.get_toc()
    if toc:
        for t in toc:
            level, title, _ = t
            toc_structure.append({
                "level": str(level),
                "text": title
            })
    
    # Create ImageInfo
    image_info = None
    if image_count > 0:
        avg_size_kb = (total_image_size / image_count) / 1024
        image_info = ImageInfo(count=image_count, avg_size_kb=round(avg_size_kb, 2))
    
    # Estimate line spacing (very approximate for PDF)
    line_spacing = {"Default": 1.2}  # Default line spacing estimate
    
    return DetailedDocumentAnalysis(
        fonts=fonts,
        images=image_info,
        line_spacing=line_spacing,
        paragraph_count=paragraph_count,
        toc_structure=toc_structure,
        metadata=metadata,
        has_color_pages=has_color_pages,
        has_color_text=has_color_text,
        colored_elements_count=colored_elements_count
    )


# ------------------------------------------------------------------ #
def process_document(file_content: bytes, file_format: str) -> Dict[str, Any]:
    """
    Estrae le proprietà del documento e, dove serve, calcola anche page_count
    convertendo prima in PDF con LibreOffice. Supporta doc, docx, odt e pdf.
    """
    fmt = file_format.lower()

    # ---------- .DOC binario ----------------------------------------
    if fmt == "doc":
        # convertiamo direttamente a PDF e usiamo le proprietà PDF
        pdf_bytes = convert_to_pdf_via_lo(file_content, "doc")
        pdf_props = extract_pdf_properties(pdf_bytes)
        return pdf_props                       # page_count già incluso

    # ---------- .DOCX ----------------------------------------------
    if fmt == "docx":
        doc_props = extract_docx_properties(file_content)
        # conta pagine via PDF
        pdf_bytes = convert_to_pdf_via_lo(file_content, "docx")
        doc_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return doc_props

    # ---------- .ODT -----------------------------------------------
    if fmt == "odt":
        odt_props = extract_odt_properties(file_content)
        pdf_bytes = convert_to_pdf_via_lo(file_content, "odt")
        odt_props["page_count"] = extract_pdf_page_count(pdf_bytes)
        return odt_props

    # ---------- .PDF ------------------------------------------------
    if fmt == "pdf":
        pdf_props = extract_pdf_properties(file_content)
        # extract_pdf_properties ora inserisce page_count
        return pdf_props

    # ---------- formato non supportato -----------------------------
    raise HTTPException(status_code=400, detail=f"Unsupported file format: {file_format}")
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
def validate_document(
    doc_props: Dict[str, Any],
    spec: DocumentSpec,
    services: Optional[Dict[str, bool]] = None
) -> Dict[str, Any]:
    """
    Restituisce:
    {
        'validations': { check_name: bool, ... },
        'is_valid': bool
    }
    Alcuni check possono essere disattivati in base ai servizi acquistati.
    """
    services = services or {}
    validations: Dict[str, bool] = {}

    # Page size 
    if services.get("layout_service"):
        validations["page_size"] = True      # superato di default
    else:
        pw_ok = abs(doc_props['page_size']['width_cm']  - spec.page_width_cm)  < 0.5
        ph_ok = abs(doc_props['page_size']['height_cm'] - spec.page_height_cm) < 0.5
        validations["page_size"] = pw_ok and ph_ok

    # Margini
    if services.get("layout_service"):
        # Se c'è il servizio impaginazione saltiamo i margini
        validations["margins"] = True
    else:
        margins = doc_props["margins"]
        top_ok    = abs(margins["top_cm"]    - spec.top_margin_cm)    < 0.5
        bottom_ok = abs(margins["bottom_cm"] - spec.bottom_margin_cm) < 0.5
        left_ok   = abs(margins["left_cm"]   - spec.left_margin_cm)   < 0.5
        right_ok  = abs(margins["right_cm"]  - spec.right_margin_cm)  < 0.5
        validations["margins"] = top_ok and bottom_ok and left_ok and right_ok
    
    # Validate TOC if required
    toc_valid = True
    if spec.requires_toc:
        toc_valid = doc_props['has_toc']
    validations['has_toc'] = toc_valid
    
    # Validate no color pages if required
    color_pages_valid = True
    if spec.no_color_pages and 'detailed_analysis' in doc_props:
        color_pages_valid = not doc_props['detailed_analysis'].has_color_pages and not doc_props['detailed_analysis'].has_color_text
    validations['no_color_pages'] = color_pages_valid
    
    # Validate no images if required
    no_images_valid = True
    if spec.no_images and 'detailed_analysis' in doc_props:
        no_images_valid = not doc_props['detailed_analysis'].images or doc_props['detailed_analysis'].images.count == 0
    validations['no_images'] = no_images_valid
    
    header_valid = True
    if hasattr(spec, 'requires_header') and spec.requires_header:
        header_valid = len(doc_props.get('headers', [])) > 0
    validations['has_header'] = header_valid
    
    footnotes_valid = True
    if hasattr(spec, 'requires_footnotes') and spec.requires_footnotes:
        footnotes_valid = len(doc_props.get('footnotes', [])) > 0
    validations['has_footnotes'] = footnotes_valid
    
    # --- pagine minime --------------------------------------------
    if spec.min_page_count > 0:
        validations['min_page_count'] = doc_props.get('page_count', 0) >= spec.min_page_count
    else:
        validations['min_page_count'] = True

    # Aggiorna validità complessiva
    is_valid = all(validations.values())
    
    return {
        'validations': validations,
        'is_valid': is_valid
    }

# ──────────────────────────────────────────────────────────────────
#  GENERATE PDF – versione “client-friendly”
# ──────────────────────────────────────────────────────────────────
def generate_validation_report(
    validation_result: ValidationResult,
    spec: DocumentSpec,
    report_format: ReportFormat,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
        Image,
        PageBreak,
        HRFlowable,
    )
    import io, datetime, pathlib

    # ── palette aziendale ─────────────────────────────────────────
    GREEN   = colors.HexColor("#198754")
    RED     = colors.HexColor("#d32f2f")
    ACCENT  = colors.HexColor("#0d6efd")     # blu Bootstrap
    BG_HEAD = colors.HexColor("#f2f4f6")     # grigio very-light
    
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

    # summary box
    status_txt  = "CONFORME" if validation_result.is_valid else "NON CONFORME"
    status_col  = GREEN if validation_result.is_valid else RED

    status_cell = Paragraph(
        f"<b><font color='{hex_(status_col)}'>{status_txt}</font></b>",
        styles["Normal"],
    )

    summary_tbl = Table(
        [
            ["Documento", validation_result.document_name],
            ["Risultato", status_cell],          # ← uso Paragraph
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

    # ───────────────────── 2) VALIDATION TABLE ────────────────────
    elements.append(Paragraph("Dettaglio verifiche", styles["Heading2"]))
    elements.append(Spacer(1, 0.2 * cm))

    check_rows = [["Verifica", "Esito"]]
    for check, ok in validation_result.validations.items():
        pretty = check.replace("_", " ").capitalize()
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

    # ───────────────────── 3) FONT DISTRIBUTION ───────────────────
    if report_format.include_charts and validation_result.detailed_analysis:
        da = validation_result.detailed_analysis
        if da.fonts:
            elements.append(Paragraph("Distribuzione font", styles["Heading2"]))
            elements.append(Spacer(1, 0.2 * cm))

            # header
            font_rows = [["Font", "Size pt → occorrenze", "Totale"]]

            # ordina i font per utilizzo desc.
            for name, info in sorted(
                da.fonts.items(), key=lambda it: it[1].count, reverse=True
            ):
                # ordina le singole size per occorrenze desc. e mandale a capo
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

    # ───────────────────── 4) RECOMMENDATIONS  ────────────────────
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

    # ───────────────────── 5) RAW JSON (opzionale) ────────────────
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
        for line in raw_json.split("\n")[:800]:  # mostra max ~800 righe
            elements.append(Paragraph(line.replace(" ", "&nbsp;"), mono))

    # ───────────────────── BUILD PDF ──────────────────────────────
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
    s = settings  # shorthand

    auth = (f"{s.ZENDESK_EMAIL}/token", s.ZENDESK_API_TOKEN)
    base = f"https://{s.ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"

    # ---- 1) upload attachment ---------------------------------
    up_res = requests.post(
        f"{base}/uploads.json?filename={pdf_name}",
        auth=auth,
        files={"file": (pdf_name, pdf_bytes, "application/pdf")},
    )
    up_res.raise_for_status()
    upload_token = up_res.json()["upload"]["token"]

    # ---- 2) create ticket -------------------------------------
    ticket_data = {
        "ticket": {
            "subject": subject,
            # SET del requester esterno
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

# =====  STATIC FILES & FRONTEND  =====
import sys, pathlib
if getattr(sys, 'frozen', False):
    BASE_DIR = pathlib.Path(sys._MEIPASS)  # cartella temp del bundle
else:
    BASE_DIR = pathlib.Path(__file__).parent
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

# redirect '/' → GUI
@app.get("/", include_in_schema=False)
async def frontend():
    return RedirectResponse(url="/static/index.html")
# =====================================

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add GZip compression for performance
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add trusted host middleware for security
if os.environ.get("ENVIRONMENT") == "production":
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["*"]  # Configure with your actual domain in production
    )

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Exception handler for uncaught exceptions
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Global exception handler for uncaught exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."}
    )
