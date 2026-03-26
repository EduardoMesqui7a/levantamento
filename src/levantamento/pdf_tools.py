from __future__ import annotations

import base64
import io
import re
from collections import Counter
from dataclasses import dataclass

import fitz  # pymupdf
from PIL import Image


@dataclass
class PDFPageData:
    page_number: int
    text: str
    used_ocr: bool = False
    graphics_summary: str = ""
    drawing_count: int = 0
    line_count: int = 0
    rect_count: int = 0
    curve_count: int = 0
    fill_count: int = 0
    image_count: int = 0
    image_data_uri: str = ""


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


def _render_page_image_data_uri(page) -> str:
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(1.75, 1.75), alpha=False)
        image_bytes = pix.tobytes("png")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:  # noqa: BLE001
        return ""


def _summarize_graphics(page) -> tuple[str, int, int, int, int, int, int]:
    drawings = []
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001
        drawings = []

    line_count = 0
    rect_count = 0
    curve_count = 0
    fill_count = 0
    op_counter: Counter[str] = Counter()

    for drawing in drawings:
        if drawing.get("fill") is not None:
            fill_count += 1
        for item in drawing.get("items", []):
            if not item:
                continue
            op = str(item[0])
            op_counter[op] += 1
            if op == "l":
                line_count += 1
            elif op == "re":
                rect_count += 1
            elif op in {"c", "qu", "v", "y"}:
                curve_count += 1

    image_count = 0
    try:
        image_count = len(page.get_images(full=True))
    except Exception:  # noqa: BLE001
        image_count = 0

    ops_summary = ", ".join(f"{key}:{value}" for key, value in op_counter.most_common(8)) or "sem vetores explícitos"
    summary = (
        f"vetores={len(drawings)}; linhas={line_count}; retângulos={rect_count}; curvas={curve_count}; "
        f"preenchimentos={fill_count}; imagens_embutidas={image_count}; operacoes={ops_summary}"
    )
    return summary, len(drawings), line_count, rect_count, curve_count, fill_count, image_count


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
        graphics_summary, drawing_count, line_count, rect_count, curve_count, fill_count, image_count = _summarize_graphics(page)
        pages.append(
            PDFPageData(
                page_number=index + 1,
                text=text,
                used_ocr=used_ocr,
                graphics_summary=graphics_summary,
                drawing_count=drawing_count,
                line_count=line_count,
                rect_count=rect_count,
                curve_count=curve_count,
                fill_count=fill_count,
                image_count=image_count,
                image_data_uri=_render_page_image_data_uri(page),
            )
        )
    return pages
