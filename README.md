# Document Validator API

A comprehensive FastAPI-based document validation service designed for publishing workflows. This application analyzes documents against specific formatting requirements, extracts detailed properties, and provides validation reports.

## 🚀 Features

- **Multi-format Document Support**: Validate PDF, DOCX, and ODT files
- **Order Text Parsing**: Extract format requirements from order descriptions
- **Detailed Document Analysis**: 
  - Page dimensions and margins
  - Font analysis with size distribution
  - Image detection and analysis
  - Table of Contents (TOC) structure
  - Color page detection
  - Header and footer analysis
- **PDF Report Generation**: Create comprehensive validation reports
- **Zendesk Integration**: Automatically create support tickets with validation results
- **Web Interface**: User-friendly Bootstrap-based frontend
- **REST API**: Complete API for programmatic access
- **In-Memory Storage**: Lightweight deployment without database requirements

## 📋 Requirements

- Python 3.8+
- LibreOffice (for document conversion)

## 🛠️ Installation

### 1. Clone the Repository

```bash
git clone https://github.com/MarcoLP1822/analisi_file2.git
cd analisi_file2
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install LibreOffice

LibreOffice is required for document conversion:

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install libreoffice
```

**macOS:**
```bash
brew install --cask libreoffice
```

**Windows:**
Download and install from [LibreOffice official website](https://www.libreoffice.org/download/download/)

### 5. Configuration

Create a `.env` file in the project root:

```env
# Zendesk Configuration (optional)
ZENDESK_SUBDOMAIN=your-subdomain
ZENDESK_EMAIL=your-email@domain.com
ZENDESK_API_TOKEN=your-api-token

# Application Settings
LOG_LEVEL=INFO
MAX_FILE_SIZE=20971520  # 20MB in bytes
SECRET_KEY=your-secret-key-here

# CORS Settings (optional)
ALLOWED_ORIGINS=*
```

## 🚀 Usage

### Starting the Server

```bash
python main.py
```

The application will be available at:
- **Web Interface**: http://127.0.0.1:8000/
- **API Documentation**: http://127.0.0.1:8000/api/docs
- **Alternative API Docs**: http://127.0.0.1:8000/api/redoc

### Web Interface

1. Open http://127.0.0.1:8000/ in your browser
2. Enter the order text with format specifications (e.g., "Formato: 17x24")
3. Upload a document file (PDF, DOCX, or ODT)
4. Click "Valida" to validate the document
5. View validation results and download reports
6. Optionally send results via email to customers

### API Usage

#### Validate Document

```bash
curl -X POST "http://127.0.0.1:8000/api/validate-order" \
  -F "order_text=Formato: 17x24
1x Servizio impaginazione testo" \
  -F "file=@document.pdf"
```

#### Generate Report

```bash
curl -X POST "http://127.0.0.1:8000/api/validation-reports/{validation_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "include_charts": true,
    "include_detailed_analysis": true,
    "include_recommendations": true
  }' \
  --output report.pdf
```

#### Create Zendesk Ticket

```bash
curl -X POST "http://127.0.0.1:8000/api/zendesk-ticket" \
  -H "Content-Type: application/json" \
  -d '{
    "validation_id": "your-validation-id",
    "customer_email": "customer@example.com",
    "subject": "Document Validation Results",
    "message": "Please find your document validation results attached."
  }'
```

#### Health Check

```bash
curl http://127.0.0.1:8000/api/health
```

## 📚 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/` | API version information |
| POST | `/api/validate-order` | Validate document against order specifications |
| POST | `/api/validation-reports/{validation_id}` | Generate PDF validation report |
| POST | `/api/zendesk-ticket` | Create Zendesk ticket with validation results |
| GET | `/api/health` | Health check endpoint |

## 🔧 Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | INFO |
| `MAX_FILE_SIZE` | Maximum upload file size in bytes | 20971520 (20MB) |
| `SECRET_KEY` | JWT secret key | INSECURE-DEV-KEY |
| `ZENDESK_SUBDOMAIN` | Zendesk subdomain | - |
| `ZENDESK_EMAIL` | Zendesk API email | - |
| `ZENDESK_API_TOKEN` | Zendesk API token | - |
| `ALLOWED_ORIGINS` | CORS allowed origins | * |

### Document Specifications

The application validates documents against the following criteria:

- **Page Dimensions**: Width and height in centimeters
- **Margins**: Top, bottom, left, and right margins
- **Table of Contents**: Presence and structure
- **Headers and Footers**: Detection and validation
- **Color Pages**: Detection of color content
- **Images**: Count and analysis
- **Fonts**: Name and size distribution
- **Page Count**: Minimum page requirements

## 🏗️ Architecture

### Project Structure

```
analisi_file2/
├── api.py                 # API route definitions
├── server.py              # Main FastAPI application
├── main.py                # Application entry point
├── models.py              # Pydantic data models
├── config.py              # Configuration settings
├── requirements.txt       # Python dependencies
├── static/                # Web interface files
│   ├── index.html         # Main web page
│   ├── js/app.js          # Frontend JavaScript
│   └── valid.ico          # Favicon
└── utils/                 # Utility modules
    ├── conversion.py      # Document conversion utilities
    ├── local_store.py     # In-memory storage
    └── order_parser.py    # Order text parsing
```

### Data Flow

1. **Document Upload**: Client uploads document via web interface or API
2. **Order Parsing**: Extract format requirements from order text
3. **Document Analysis**: Process document to extract properties
4. **Validation**: Compare document properties against specifications
5. **Report Generation**: Create PDF reports with validation results
6. **Storage**: Store results in-memory for later retrieval
7. **Integration**: Optionally create Zendesk tickets

### Document Processing Pipeline

1. **Format Detection**: Identify file type (PDF, DOCX, ODT)
2. **Property Extraction**: Extract dimensions, margins, fonts, etc.
3. **Conversion**: Convert to PDF for consistent analysis (ODT/DOCX)
4. **Detailed Analysis**: Font counting, image analysis, TOC extraction
5. **Validation**: Compare against order specifications
6. **Report Creation**: Generate formatted PDF reports

## 🧪 Development

### Running in Development Mode

```bash
uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

### Testing

The application includes basic validation and error handling. For development:

1. Test document upload with various formats
2. Verify order text parsing with different formats
3. Check validation logic with edge cases
4. Test report generation
5. Validate Zendesk integration (if configured)

### Adding New Document Formats

To add support for new document formats:

1. Add format detection in `process_document()` function
2. Implement property extraction function
3. Add conversion logic if needed
4. Update validation logic
5. Test thoroughly

## 📝 Order Text Format

The order text should include format specifications. Example:

```
Formato: 17x24
1x Servizio impaginazione testo
Margini: 2cm
TOC richiesto: Sì
```

Supported format patterns:
- `Formato: 17x24` (width x height in cm)
- `Formato: 17×24` (with multiplication symbol)
- `Formato: 17*24` (with asterisk)

## 🔒 Security

- JWT-based authentication (configurable)
- File upload size limits
- CORS configuration
- Input validation with Pydantic
- Secure file handling

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is part of the Youcanprint document validation workflow.

## 🆘 Support

For support and questions:
- Check the API documentation at `/api/docs`
- Review the configuration options
- Ensure LibreOffice is properly installed
- Verify all dependencies are installed correctly

## 🔧 Troubleshooting

### Common Issues

**LibreOffice not found:**
```
Ensure LibreOffice is installed and 'soffice' command is in PATH
```

**Module import errors:**
```
pip install -r requirements.txt
```

**File upload errors:**
```
Check MAX_FILE_SIZE setting and file permissions
```

**Zendesk integration issues:**
```
Verify ZENDESK_* environment variables are correctly set
```