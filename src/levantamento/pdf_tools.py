from __future__ import annotations

import io
import re
from dataclasses import dataclass

import fitz  # pymupdf
from PIL import Image


@dataclass
class PDFPageData:
    page_number: int
    text: str
    used_ocr: bool = False


def _normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ocr_page(page) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""

    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image_bytes = pix.tobytes("png")
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image, lang="por+eng")
    except Exception:  # noqa: BLE001
        return ""


def extract_pdf_pages(file_bytes: bytes) -> list[PDFPageData]:
    if not file_bytes:
        raise ValueError("Empty file received.")

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ValueError("The uploaded file could not be opened as a PDF.") from exc

    pages: list[PDFPageData] = []
    for index in range(doc.page_count):
        page = doc.load_page(index)
        text = _normalize_text(page.get_text("text"))
        used_ocr = False
        if len(text) < 40:
            ocr_text = _normalize_text(_ocr_page(page))
            if ocr_text:
                text = ocr_text
                used_ocr = True
        pages.append(PDFPageData(page_number=index + 1, text=text, used_ocr=used_ocr))
    return pages
