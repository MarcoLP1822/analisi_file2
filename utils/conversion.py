# utils/conversion.py
import io
import pathlib
import subprocess
import tempfile

import PyPDF2


# ------------------------------------------------------------------ #
def convert_to_pdf_via_lo(src_bytes: bytes, ext: str) -> bytes:
    """
    Converte un file (doc, docx, odt) in PDF usando LibreOffice.
    Restituisce i byte del PDF.
    
    Raises:
        FileNotFoundError: Se LibreOffice non è installato o non è nel PATH
        subprocess.CalledProcessError: Se la conversione fallisce
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src_path = pathlib.Path(tmp) / f"input.{ext.lower()}"
            pdf_path = pathlib.Path(tmp) / "input.pdf"
            src_path.write_bytes(src_bytes)

            # LibreOffice deve essere nel PATH
            result = subprocess.run(
                [
                    "soffice", "--headless",
                    "--convert-to", "pdf",
                    str(src_path),
                    "--outdir", str(src_path.parent)
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30  # timeout di 30 secondi
            )
            
            if not pdf_path.exists():
                raise RuntimeError(f"LibreOffice non è riuscito a creare il PDF. Stderr: {result.stderr}")
                
            return pdf_path.read_bytes()
            
    except FileNotFoundError:
        raise FileNotFoundError(
            "LibreOffice non trovato. Installa LibreOffice e assicurati che 'soffice' sia nel PATH."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Timeout durante la conversione del documento con LibreOffice.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Errore durante la conversione LibreOffice: {e.stderr}")

# ------------------------------------------------------------------ #
def extract_pdf_page_count(pdf_bytes: bytes) -> int:
    """
    Ritorna il numero di pagine di un PDF (byte in memoria).
    
    Args:
        pdf_bytes: I byte del file PDF
        
    Returns:
        int: Numero di pagine del PDF
        
    Raises:
        ValueError: Se il file non è un PDF valido
    """
    try:
        return len(PyPDF2.PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception as e:
        raise ValueError(f"File PDF non valido o corrotto: {str(e)}")
