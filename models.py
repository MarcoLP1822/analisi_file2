# models.py  – versione ripulita (solo le due classi interessate)
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, EmailStr

class DocumentSpec(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str

    # Dimensioni pagina (cm)
    page_width_cm: float
    page_height_cm: float

    # Margini (cm)
    top_margin_cm: float
    bottom_margin_cm: float
    left_margin_cm: float
    right_margin_cm: float

    # Requisiti opzionali
    requires_toc: bool = False
    no_color_pages: bool = False
    no_images: bool = False
    requires_header: bool = False
    requires_footnotes: bool = False
    min_page_count: int = 0

    # Metadati
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None


class DocumentSpecCreate(BaseModel):
    """
    Versione usata per la POST di creazione da API.
    Stessi campi di DocumentSpec ma senza id/created_at/created_by.
    """
    name: str
    page_width_cm: float
    page_height_cm: float
    top_margin_cm: float
    bottom_margin_cm: float
    left_margin_cm: float
    right_margin_cm: float

    requires_toc: bool = False
    no_color_pages: bool = False
    no_images: bool = False
    requires_header: bool = False
    requires_footnotes: bool = False
    min_page_count: int = 0

class FontInfo(BaseModel):
    sizes: List[float]
    count: int

class ImageInfo(BaseModel):
    count: int
    avg_size_kb: float

class DetailedDocumentAnalysis(BaseModel):
    fonts: Dict[str, FontInfo] = {}
    images: Optional[ImageInfo] = None
    line_spacing: Dict[str, float] = {}
    paragraph_count: int = 0
    toc_structure: List[Dict[str, str]] = []
    metadata: Dict[str, str] = {}
    has_color_pages: bool = False
    has_color_text: bool = False
    colored_elements_count: int = 0

class ValidationResult(BaseModel):
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    document_name: str
    spec_id: str
    spec_name: str
    file_format: str
    validations: Dict[str, bool]
    is_valid: bool
    detailed_analysis: Optional[DetailedDocumentAnalysis] = None
    user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    raw_props: Optional[Dict[str, Any]] = None

class EmailTemplate(BaseModel):
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    subject: str
    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None

class EmailTemplateCreate(BaseModel):
    subject: str
    body: str

class ReportFormat(BaseModel):
    include_charts: bool = True
    include_detailed_analysis: bool = True
    include_recommendations: bool = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None