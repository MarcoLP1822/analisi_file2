# utils/conversion.py
import subprocess, tempfile, pathlib, io
import PyPDF2

# ------------------------------------------------------------------ #
def convert_to_pdf_via_lo(src_bytes: bytes, ext: str) -> bytes:
    """
    Converte un file (doc, docx, odt) in PDF usando LibreOffice.
    Restituisce i byte del PDF.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src_path = pathlib.Path(tmp) / f"input.{ext.lower()}"
        pdf_path = pathlib.Path(tmp) / "input.pdf"
        src_path.write_bytes(src_bytes)

        # LibreOffice deve essere nel PATH
        subprocess.run(
            [
                "soffice", "--headless",
                "--convert-to", "pdf",
                str(src_path),
                "--outdir", str(src_path.parent)
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        return pdf_path.read_bytes()

# ------------------------------------------------------------------ #
def extract_pdf_page_count(pdf_bytes: bytes) -> int:
    """Ritorna il numero di pagine di un PDF (byte in memoria)."""
    return len(PyPDF2.PdfReader(io.BytesIO(pdf_bytes)).pages)
