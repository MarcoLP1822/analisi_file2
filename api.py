from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Response, Depends, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import time
import io
import os
import logging
import tempfile

from models import (
    Token, TokenData, User, UserInDB, UserCreate,
    DocumentSpec, DocumentSpecCreate,
    FontInfo, ImageInfo, DetailedDocumentAnalysis,
    ValidationResult, EmailTemplate, EmailTemplateCreate,
    ReportFormat
)
from db import db
from server import (
    pwd_context, oauth2_scheme, SECRET_KEY, ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    verify_password, get_password_hash, get_user, authenticate_user,
    create_access_token, get_current_user, get_current_active_user,
    extract_docx_properties, extract_docx_detailed_analysis,
    extract_odt_properties, extract_pdf_properties, extract_pdf_detailed_analysis,
    process_document, validate_document, generate_validation_report
)

logger = logging.getLogger("document_validator")

api_router = APIRouter(prefix="/api")

# API Routes
@api_router.get("/", status_code=status.HTTP_200_OK)
async def root():
    """Root endpoint for the API"""
    return {"message": "Document Validator API", "version": "2.0.0"}

# Authentication endpoints
@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/users", response_model=User)
async def create_user(user: UserCreate):
    existing_user = await get_user(user.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    hashed_password = get_password_hash(user.password)
    user_obj = UserInDB(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        full_name=user.full_name
    )
    await db.users.insert_one(user_obj.model_dump())
    return User(**user_obj.model_dump(exclude={'hashed_password'}))

@api_router.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user


# Document Specification Endpoints
@api_router.post("/specs", response_model=DocumentSpec, status_code=status.HTTP_201_CREATED)
async def create_spec(spec: DocumentSpecCreate):
    try:
        spec_dict = spec.model_dump()
        spec_obj = DocumentSpec(**spec_dict)
        await db.document_specs.insert_one(spec_obj.model_dump())
        return spec_obj
    except Exception as e:
        logger.error(f"Error creating specification: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating specification"
        )

@api_router.get("/specs", response_model=List[DocumentSpec])
async def get_specs():
    try:
        specs = await db.document_specs.find({}).to_list(1000)
        return [DocumentSpec(**spec) for spec in specs]
    except Exception as e:
        logger.error(f"Error retrieving specifications: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving specifications"
        )

@api_router.get("/specs/{spec_id}", response_model=DocumentSpec)
async def get_spec(spec_id: str):
    try:
        spec = await db.document_specs.find_one({"id": spec_id})
        if not spec:
            raise HTTPException(status_code=404, detail="Specification not found")
        return DocumentSpec(**spec)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving specification {spec_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving specification"
        )

@api_router.delete("/specs/{spec_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spec(spec_id: str):
    try:
        result = await db.document_specs.delete_one({"id": spec_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Specification not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting specification {spec_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error deleting specification"
        )


# Document Validation Endpoint
@api_router.post("/validate", response_model=ValidationResult)
async def validate_document_file(
    file: UploadFile = File(...),
    spec_id: str = Form(...)
):
    start_time = time.time()
    try:
        max_size = int(os.environ.get('MAX_FILE_SIZE', 20971520))  # 20MB default
        file_size = 0
        file_content = b''
        chunk_size = 1024 * 1024  # 1MB
        
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            file_content += chunk
            file_size += len(chunk)
            if file_size > max_size:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large. Max size is {max_size/1024/1024:.1f} MB"
                )
        spec_data = await db.document_specs.find_one({"id": spec_id})
        if not spec_data:
            raise HTTPException(status_code=404, detail="Specification not found")
        spec = DocumentSpec(**spec_data)
        file_extension = file.filename.split('.')[-1].lower()
        if file_extension not in ['docx', 'odt', 'pdf']:
            raise HTTPException(status_code=400, detail="Unsupported file format")
        doc_props = await process_document(file_content, file_extension)
        validation = validate_document(doc_props, spec)
        result = ValidationResult(
            document_name=file.filename,
            spec_id=spec_id,
            spec_name=spec.name,
            file_format=file_extension,
            validations=validation['validations'],
            is_valid=validation['is_valid'],
            detailed_analysis=doc_props.get('detailed_analysis')
        )
        await db.validation_results.insert_one(result.model_dump())
        processing_time = time.time() - start_time
        logger.info(f"Validation completed in {processing_time:.2f}s for file {file.filename}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating document: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating document: {e}"
        )
        
@api_router.post("/validate/{spec_id}", response_model=ValidationResult)
async def validate_document_file_path(
    spec_id: str,
    file: UploadFile = File(...),
):
    # riutilizza la funzione già pronta
    return await validate_document_file(file=file, spec_id=spec_id)

# Email Templates Endpoints
@api_router.post("/email-templates", response_model=EmailTemplate, status_code=status.HTTP_201_CREATED)
async def create_email_template(template: EmailTemplateCreate):
    try:
        template_dict = template.model_dump()
        template_obj = EmailTemplate(**template_dict)
        await db.email_templates.insert_one(template_obj.model_dump())
        return template_obj
    except Exception as e:
        logger.error(f"Error creating email template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating email template"
        )

@api_router.get("/email-templates", response_model=List[EmailTemplate])
async def get_email_templates():
    try:
        templates = await db.email_templates.find({}).to_list(1000)
        return [EmailTemplate(**template) for template in templates]
    except Exception as e:
        logger.error(f"Error retrieving email templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving email templates"
        )

@api_router.get("/email-templates/{template_id}", response_model=EmailTemplate)
async def get_email_template(template_id: str):
    try:
        template = await db.email_templates.find_one({"id": template_id})
        if not template:
            raise HTTPException(status_code=404, detail="Email template not found")
        return EmailTemplate(**template)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving email template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving email template"
        )

@api_router.delete("/email-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_template(template_id: str):
    try:
        result = await db.email_templates.delete_one({"id": template_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Email template not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting email template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error deleting email template"
        )


# Validation Results Endpoints
@api_router.get("/validation-results", response_model=List[ValidationResult])
async def get_validation_results():
    try:
        results = await db.validation_results.find().to_list(1000)
        return [ValidationResult(**result) for result in results]
    except Exception as e:
        logger.error(f"Error retrieving validation results: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving validation results"
        )

@api_router.get("/validation-results/{result_id}", response_model=ValidationResult)
async def get_validation_result(result_id: str):
    try:
        result = await db.validation_results.find_one({"id": result_id})
        if not result:
            raise HTTPException(status_code=404, detail="Validation result not found")
        return ValidationResult(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving validation result {result_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving validation result"
        )


# Report generation endpoint
@api_router.post("/validation-reports/{validation_id}")
async def generate_report(validation_id: str, report_format: ReportFormat):
    try:
        validation_data = await db.validation_results.find_one({"id": validation_id})
        if not validation_data:
            raise HTTPException(status_code=404, detail="Validation result not found")

        validation_result = ValidationResult(**validation_data)

        spec_data = await db.document_specs.find_one({"id": validation_result.spec_id})
        if not spec_data:
            raise HTTPException(status_code=404, detail="Specification not found")

        spec = DocumentSpec(**spec_data)

        pdf_report = generate_validation_report(validation_result, spec, report_format)

        return Response(
            content=pdf_report,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=validation_report_{validation_id}.pdf"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generating report"
        )

# ------------------------------------------------------------------ #
# === VALIDAZIONE BASATA SU TESTO DELL'ORDINE ======================= #
from utils.order_parser import parse_order   # in cima al file era già importato?

@api_router.post("/validate-order", response_model=ValidationResult)
async def validate_with_order(
    request: Request,
    order_text: str = Form(...),
    file: UploadFile = File(...),
):
    """
    • `order_text`  → testo completo incollato dall'utente
    • `file`        → documento da validare
    Genera al volo una DocumentSpec derivata dall'ordine e applica
    le regole dinamiche (salto check dimensioni se c'è impaginazione).
    """
    try:
        # 1) parse ordine
        parsed = parse_order(order_text)
        width_cm, height_cm = parsed["final_format_cm"]
        services = parsed["services"]

        # 2) costruiamo una specifica "on‑the‑fly"
        spec = DocumentSpec(
            name="Specifica derivata da ordine",
            page_width_cm=width_cm,
            page_height_cm=height_cm,
            top_margin_cm=0,
            bottom_margin_cm=0,
            left_margin_cm=0,
            right_margin_cm=0,
            min_page_count=40,           # vincolo fisso richiesto
        )

        # 3) processiamo il documento
        file_bytes = await file.read()
        doc_props = await process_document(file_bytes, file.filename.split(".")[-1])

        # 4) validiamo con servizi dinamici
        validation = validate_document(doc_props, spec, services)

        # 5) salviamo (facoltativo) e rispondiamo
        result = ValidationResult(
            document_name=file.filename,
            spec_id=spec.id,
            spec_name=spec.name,
            file_format=file.filename.split(".")[-1].lower(),
            validations=validation["validations"],
            is_valid=validation["is_valid"],
            detailed_analysis=doc_props.get("detailed_analysis"),
        )
        # se vuoi persistere:
        # await db.validation_results.insert_one(result.model_dump())

        return result

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ex:
        logger.error(f"Errore in /validate-order: {ex}")
        raise HTTPException(status_code=500, detail="Errore interno")
# ------------------------------------------------------------------ #

# Health check endpoint
@api_router.get("/health")
async def health_check():
    try:
        await db.command("ping")
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )