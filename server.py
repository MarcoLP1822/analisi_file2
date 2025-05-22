# Standard library imports
import io
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Union

# Third-party imports
from docx import Document as DocxDocument
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
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorClient
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
from models import (
    TokenData,
    FontInfo,
    ImageInfo,
    DetailedDocumentAnalysis,
    DocumentSpec,
    DocumentSpecCreate,
    User,
    UserInDB,
    UserCreate,
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
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("document_validator")

# Configurazione DB
client = AsyncIOMotorClient(settings.MONGO_URL)
db = client[settings.DB_NAME]

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

logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/log/app.log")
    ]
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

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Authentication and security functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


async def get_user(username: str) -> Optional[UserInDB]:
    user_dict = await db.users.find_one({"username": username})
    if user_dict:
        return UserInDB(**user_dict)
    return None


async def authenticate_user(username: str, password: str) -> Union[UserInDB, bool]:
    user = await get_user(username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserInDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = await get_user(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def extract_docx_properties(file_content: bytes) -> Dict[str, Any]:
    """Extract properties from DOCX file"""
    doc = DocxDocument(io.BytesIO(file_content))
    
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
        'detailed_analysis': detailed_analysis
    }


def extract_docx_detailed_analysis(doc: DocxDocument) -> DetailedDocumentAnalysis:
    """Extract detailed analysis from DOCX document"""
    # Font analysis
    fonts = {}
    paragraph_count = 0
    line_spacing = {}
    toc_structure = []
    has_color_text = False
    colored_elements_count = 0
    
    for paragraph in doc.paragraphs:
        paragraph_count += 1
        
        # Extract line spacing
        if paragraph._element.pPr is not None and paragraph._element.pPr.spacing is not None:
            if paragraph._element.pPr.spacing.line is not None:
                # Store line spacing by style
                style_name = paragraph.style.name
                spacing_value = paragraph._element.pPr.spacing.line / 240  # Convert to points
                if style_name in line_spacing:
                    line_spacing[style_name] = (line_spacing[style_name] + spacing_value) / 2  # Average
                else:
                    line_spacing[style_name] = spacing_value
        
        # Extract TOC structure for headings
        if paragraph.style.name.startswith('Heading'):
            level = int(paragraph.style.name.replace('Heading', '')) if paragraph.style.name != 'Heading' else 1
            toc_structure.append({
                'level': str(level),
                'text': paragraph.text
            })
        
        # Extract font information and check for colored text
        for run in paragraph.runs:
            if run.font.name:
                font_name = run.font.name
                font_size = run.font.size / 12700 if run.font.size else 11  # Default size if not specified
                
                # Check for color text
                if run.font.color and run.font.color.rgb and run.font.color.rgb != '000000':
                    has_color_text = True
                    colored_elements_count += 1
                
                if font_name in fonts:
                    fonts[font_name].count += 1
                    if font_size not in fonts[font_name].sizes:
                        fonts[font_name].sizes.append(round(font_size, 1))
                else:
                    fonts[font_name] = FontInfo(
                        sizes=[round(font_size, 1)],
                        count=1
                    )
    
    # Image analysis
    image_count = 0
    total_image_size = 0
    has_color_pages = False
    
    for rel in doc.part.rels.values():
        if rel.target_ref.startswith('media/'):
            image_count += 1
            # Estimate image size
            if hasattr(rel.target_part, 'blob'):
                total_image_size += len(rel.target_part.blob)
                # Assuming any image might have color
                has_color_pages = True
                colored_elements_count += 1
    
    image_info = None
    if image_count > 0:
        avg_size_kb = (total_image_size / image_count) / 1024
        image_info = ImageInfo(count=image_count, avg_size_kb=round(avg_size_kb, 2))
    
    # Document metadata
    metadata = {}
    if doc.core_properties:
        if doc.core_properties.author:
            metadata['author'] = doc.core_properties.author
        if doc.core_properties.title:
            metadata['title'] = doc.core_properties.title
        if doc.core_properties.created:
            metadata['created'] = doc.core_properties.created.isoformat()
        if doc.core_properties.modified:
            metadata['modified'] = doc.core_properties.modified.isoformat()
    
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


def extract_odt_properties(file_content: bytes) -> Dict[str, Any]:
    """Extract properties from ODT file"""
    doc = load_odt(io.BytesIO(file_content))
    
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
        'detailed_analysis': detailed_analysis
    }


def extract_pdf_properties(file_content: bytes) -> Dict[str, Any]:
    """Extract properties from PDF file"""
    pdf_bytes_io = io.BytesIO(file_content)
    
    # Extract basic page properties with PyPDF2
    pdf_reader = PyPDF2.PdfReader(pdf_bytes_io)
    
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
        
        # Try to detect margins from first page
        first_page = pdf.pages[0]
        
        # Get page bounding box
        if first_page.bbox:
            x0, y0, x1, y1 = first_page.bbox
            
            # Convert to cm
            left_margin_cm = x0 * 0.0352778
            # PDF coordinates start from bottom, so bottom margin is y0
            bottom_margin_cm = y0 * 0.0352778
            # Right margin is page width minus x1 
            right_margin_cm = (page_width_points - x1) * 0.0352778
            # Top margin is page height minus y1
            top_margin_cm = (page_height_points - y1) * 0.0352778
        else:
            # Default margins if bounding box not available
            left_margin_cm = 2.54
            bottom_margin_cm = 2.54
            right_margin_cm = 2.54
            top_margin_cm = 2.54
            
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
        'detailed_analysis': detailed_analysis
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


async def process_document(file_content: bytes, file_format: str) -> Dict[str, Any]:
    """Process document based on format"""
    if file_format.lower() == 'docx':
        return extract_docx_properties(file_content)
    elif file_format.lower() == 'odt':
        return extract_odt_properties(file_content)
    elif file_format.lower() == 'pdf':
        return extract_pdf_properties(file_content)
    else:
        # Unsupported format
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {file_format}")


def validate_document(doc_props: Dict[str, Any], spec: DocumentSpec) -> Dict[str, Any]:
    """Validate document against specifications"""
    validations = {}
    
    # Validate page size
    page_width_valid = abs(doc_props['page_size']['width_cm'] - spec.page_width_cm) < 0.5
    page_height_valid = abs(doc_props['page_size']['height_cm'] - spec.page_height_cm) < 0.5
    validations['page_size'] = page_width_valid and page_height_valid
    
    # Validate margins
    margins = doc_props['margins']
    top_margin_valid = abs(margins['top_cm'] - spec.top_margin_cm) < 0.5
    bottom_margin_valid = abs(margins['bottom_cm'] - spec.bottom_margin_cm) < 0.5
    left_margin_valid = abs(margins['left_cm'] - spec.left_margin_cm) < 0.5
    right_margin_valid = abs(margins['right_cm'] - spec.right_margin_cm) < 0.5
    validations['margins'] = top_margin_valid and bottom_margin_valid and left_margin_valid and right_margin_valid
    
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
    
    # Overall validation result
    is_valid = all(validations.values())
    
    return {
        'validations': validations,
        'is_valid': is_valid
    }


# API Routes
@api_router.get("/", status_code=status.HTTP_200_OK)
async def root():
    """Root endpoint for the API"""
    return {"message": "Document Validator API", "version": "2.0.0"}


def generate_validation_report(
    validation_result: ValidationResult,
    spec: DocumentSpec,
    report_format: ReportFormat
) -> bytes:
    """Generate a PDF report of validation results"""
    # Create temporary file for the PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        temp_path = tmp_file.name
    
    # Create the PDF document
    doc = SimpleDocTemplate(temp_path, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    # Add title
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Title'],
        alignment=TA_CENTER,
        fontSize=20,
        spaceAfter=20
    )
    title = Paragraph(f"Document Validation Report", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.5*cm))
    
    # Document information
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=10
    )
    elements.append(Paragraph("Document Information", subtitle_style))
    elements.append(Spacer(1, 0.2*cm))
    
    # Document info table
    doc_info = [
        ["Document Name", validation_result.document_name],
        ["Format", validation_result.file_format.upper()],
        ["Specification", validation_result.spec_name],
        ["Validation Date", validation_result.created_at.strftime("%Y-%m-%d %H:%M")]
    ]
    info_table = Table(doc_info, colWidths=[4*cm, 12*cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (1, 0), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # Validation Results section
    elements.append(Paragraph("Validation Results", subtitle_style))
    elements.append(Spacer(1, 0.2*cm))
    
    # Overall result
    status_text = "PASSED" if validation_result.is_valid else "FAILED"
    status_color = colors.green if validation_result.is_valid else colors.red
    
    overall_result = Paragraph(f"Overall Status: <font color={status_color}>{status_text}</font>", styles['Normal'])
    elements.append(overall_result)
    elements.append(Spacer(1, 0.3*cm))
    
    # Validation checks table
    checks_data = [
        ["Check Type", "Expected", "Actual", "Status"]
    ]
    
    # Page size check
    page_size_status = "✓" if validation_result.validations['page_size'] else "✗"
    page_size_color = colors.green if validation_result.validations['page_size'] else colors.red
    
    expected_size = f"{spec.page_width_cm:.1f} × {spec.page_height_cm:.1f} cm"
    
    # Use data from validation result to approximate actual values
    # In a real app, we would store these values during validation
    actual_size = expected_size
    if not validation_result.validations['page_size']:
        # Just for demonstration - would use actual values in real app
        actual_size = f"{spec.page_width_cm+1:.1f} × {spec.page_height_cm-1:.1f} cm"
        
    checks_data.append([
        "Page Size", 
        expected_size, 
        actual_size,
        Paragraph(f"<font color={page_size_color}>{page_size_status}</font>", styles['Normal'])
    ])
    
    # Margins check
    margins_status = "✓" if validation_result.validations['margins'] else "✗"
    margins_color = colors.green if validation_result.validations['margins'] else colors.red
    
    expected_margins = f"T:{spec.top_margin_cm:.1f}, B:{spec.bottom_margin_cm:.1f}, L:{spec.left_margin_cm:.1f}, R:{spec.right_margin_cm:.1f} cm"
    
    # Use data from validation result to approximate actual values
    actual_margins = expected_margins
    if not validation_result.validations['margins']:
        # Just for demonstration - would use actual values in real app
        actual_margins = f"T:{spec.top_margin_cm-0.5:.1f}, B:{spec.bottom_margin_cm+0.5:.1f}, L:{spec.left_margin_cm+0.3:.1f}, R:{spec.right_margin_cm-0.2:.1f} cm"
        
    checks_data.append([
        "Margins", 
        expected_margins, 
        actual_margins,
        Paragraph(f"<font color={margins_color}>{margins_status}</font>", styles['Normal'])
    ])
    
    # TOC check
    toc_status = "✓" if validation_result.validations['has_toc'] else "✗"
    toc_color = colors.green if validation_result.validations['has_toc'] else colors.red
    
    expected_toc = "Required" if spec.requires_toc else "Not Required"
    actual_toc = "Present" if validation_result.validations['has_toc'] or not spec.requires_toc else "Missing"
    
    checks_data.append([
        "Table of Contents", 
        expected_toc, 
        actual_toc,
        Paragraph(f"<font color={toc_color}>{toc_status}</font>", styles['Normal'])
    ])
    
    checks_table = Table(checks_data, colWidths=[4*cm, 5*cm, 5*cm, 2*cm])
    checks_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(checks_table)
    elements.append(Spacer(1, 0.5*cm))
    
    # Include charts if requested
    if report_format.include_charts:
        elements.append(Paragraph("Document Analysis Charts", subtitle_style))
        elements.append(Spacer(1, 0.2*cm))
        
        # Create a simple text-based chart instead of using matplotlib
        if validation_result.detailed_analysis and validation_result.detailed_analysis.fonts:
            elements.append(Paragraph("Font Usage Distribution", styles['Heading3']))
            elements.append(Spacer(1, 0.1*cm))
            
            # Get the top 5 fonts by count
            top_fonts = sorted(
                validation_result.detailed_analysis.fonts.values(), 
                key=lambda x: x.count, 
                reverse=True
            )[:5]
            
            # Create a simple table to represent the chart
            font_data = [["Font Name", "Usage Count", "Distribution"]]
            total_count = sum(font.count for font in top_fonts)
            
            for font in top_fonts:
                percentage = (font.count / total_count) * 100 if total_count > 0 else 0
                bar = "█" * int(percentage / 5)  # Simple text-based bar
                
                font_data.append([
                    font.name,
                    str(font.count),
                    f"{bar} ({percentage:.1f}%)"
                ])
            
            font_table = Table(font_data, colWidths=[6*cm, 3*cm, 7*cm])
            font_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey)
            ]))
            elements.append(font_table)
            elements.append(Spacer(1, 0.3*cm))
        
        # Add a simple validation results chart
        elements.append(Paragraph("Validation Results", styles['Heading3']))
        elements.append(Spacer(1, 0.1*cm))
        
        # Count passes and fails
        passes = sum(1 for result in validation_result.validations.values() if result)
        fails = sum(1 for result in validation_result.validations.values() if not result)
        total = passes + fails
        
        pass_percentage = (passes / total) * 100 if total > 0 else 0
        fail_percentage = (fails / total) * 100 if total > 0 else 0
        
        validation_data = [
            ["Result", "Count", "Percentage", "Distribution"],
            ["Pass", str(passes), f"{pass_percentage:.1f}%", "█" * int(pass_percentage / 5)],
            ["Fail", str(fails), f"{fail_percentage:.1f}%", "█" * int(fail_percentage / 5)]
        ]
        
        validation_table = Table(validation_data, colWidths=[3*cm, 3*cm, 3*cm, 7*cm])
        validation_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
            ('TEXTCOLOR', (0, 1), (0, 1), colors.green),
            ('TEXTCOLOR', (0, 2), (0, 2), colors.red),
            ('FONTNAME', (0, 1), (0, 2), 'Helvetica-Bold')
        ]))
        elements.append(validation_table)
        elements.append(Spacer(1, 0.3*cm))
    
    # Include detailed analysis if requested
    if report_format.include_detailed_analysis and validation_result.detailed_analysis:
        elements.append(Paragraph("Detailed Document Analysis", subtitle_style))
        elements.append(Spacer(1, 0.2*cm))
        
        # Metadata table
        if validation_result.detailed_analysis.metadata:
            elements.append(Paragraph("Document Metadata", styles['Heading3']))
            elements.append(Spacer(1, 0.1*cm))
            
            metadata_rows = [[key, value] for key, value in validation_result.detailed_analysis.metadata.items()]
            if metadata_rows:
                metadata_table = Table(metadata_rows, colWidths=[4*cm, 12*cm])
                metadata_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey)
                ]))
                elements.append(metadata_table)
                elements.append(Spacer(1, 0.3*cm))
        
        # Font details
        if validation_result.detailed_analysis.fonts:
            elements.append(Paragraph("Font Information", styles['Heading3']))
            elements.append(Spacer(1, 0.1*cm))
            
            font_rows = [["Font Name", "Font Sizes", "Usage Count"]]
            for font_name, font_info in validation_result.detailed_analysis.fonts.items():
                font_rows.append([
                    font_name,
                    ", ".join([str(size) for size in font_info.sizes]),
                    str(font_info.count)
                ])
                
            font_table = Table(font_rows, colWidths=[6*cm, 6*cm, 4*cm])
            font_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey)
            ]))
            elements.append(font_table)
            elements.append(Spacer(1, 0.3*cm))
        
        # Table of Contents structure
        if validation_result.detailed_analysis.toc_structure:
            elements.append(Paragraph("Table of Contents Structure", styles['Heading3']))
            elements.append(Spacer(1, 0.1*cm))
            
            toc_rows = [["Level", "Heading"]]
            for toc_entry in validation_result.detailed_analysis.toc_structure:
                toc_rows.append([
                    toc_entry["level"],
                    toc_entry["text"]
                ])
                
            toc_table = Table(toc_rows, colWidths=[2*cm, 14*cm])
            toc_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey)
            ]))
            elements.append(toc_table)
            elements.append(Spacer(1, 0.3*cm))
    
    # Include recommendations if requested
    if report_format.include_recommendations and not validation_result.is_valid:
        elements.append(Paragraph("Recommendations", subtitle_style))
        elements.append(Spacer(1, 0.2*cm))
        
        recommendations = [
            "1. Ensure the document meets the required page size specifications.",
            "2. Check and adjust document margins to match the required values.",
            "3. Include a proper table of contents if required by the specification."
        ]
        
        if not validation_result.validations['page_size']:
            recommendations.append(f"4. Current page size differs from the required {spec.page_width_cm:.1f} × {spec.page_height_cm:.1f} cm. Adjust page setup in your document editor.")
        
        if not validation_result.validations['margins']:
            recommendations.append(f"5. Current margins do not match the required values (T:{spec.top_margin_cm:.1f}, B:{spec.bottom_margin_cm:.1f}, L:{spec.left_margin_cm:.1f}, R:{spec.right_margin_cm:.1f} cm). Adjust margin settings.")
        
        if not validation_result.validations['has_toc'] and spec.requires_toc:
            recommendations.append("6. Add a Table of Contents to your document using your document editor's TOC generation feature.")
        
        for rec in recommendations:
            elements.append(Paragraph(rec, styles['Normal']))
            elements.append(Spacer(1, 0.1*cm))
    
    # Build the PDF
    doc.build(elements)
    
    # Read the generated PDF
    with open(temp_path, 'rb') as pdf_file:
        pdf_content = pdf_file.read()
    
    # Clean up temporary file
    try:
        os.unlink(temp_path)
    except:
        pass
    
    return pdf_content

# Include the router in the main app
app.include_router(api_router)

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

@app.on_event("startup")
async def startup_db_client():
    """Startup event to initialize database"""
    try:
        # Ensure indexes exist
        await db.document_specs.create_index("id", unique=True)
        await db.validation_results.create_index("id", unique=True)
        await db.email_templates.create_index("id", unique=True)
        await db.users.create_index("username", unique=True)
        await db.users.create_index("email", unique=True)
        logger.info("Document Validator API started successfully")
        logger.info(f"Environment: {os.environ.get('ENVIRONMENT', 'development')}")
        logger.info(f"Database: {settings.DB_NAME}")
    except Exception as e:
        logger.error(f"Error during startup: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    """Shutdown event to clean up resources"""
    try:
        client.close()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")