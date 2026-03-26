from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from src.levantamento.models import EAPItem, MaterialItem
from src.levantamento.pdf_tools import extract_pdf_pages


def _clip(text: str, limit: int = 7000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[TRUNCATED]"


def _compile_document_text(pages) -> str:
    chunks = []
    for page in pages:
        header = f"[PAGE {page.page_number} | OCR={page.used_ocr}]"
        chunks.append(f"{header}\n{page.text}")
    return "\n\n".join(chunks)


def _heuristic_extract(document_text: str) -> dict[str, Any]:
    lines = [line.strip() for line in document_text.splitlines() if line.strip()]
    keywords = [
        "concreto",
        "alvenaria",
        "reboco",
        "estrutura",
        "porta",
        "janela",
        "tubo",
        "fiação",
        "cabo",
        "telhado",
        "piso",
        "revestimento",
    ]
    hits = []
    for line in lines:
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            hits.append(line)

    if not hits:
        hits = lines[:12]

    eap = [
        EAPItem(code="1", name="Levantamento preliminar", description="Auto-generated fallback structure", confidence=0.42),
        EAPItem(code="1.1", name="Leitura do projeto", description="Review drawings and identify systems", confidence=0.42),
        EAPItem(code="1.2", name="EAP por sistemas", description="Breakdown by discipline and construction system", confidence=0.42),
    ]
    materials = []
    for idx, hit in enumerate(hits[:18], start=1):
        materials.append(
            MaterialItem(
                description=hit[:120],
                unit="un",
                quantity="1",
                source=f"Fallback line {idx}",
                confidence=0.3,
                category="Heuristic",
            )
        )

    return {
        "project_type": "Unknown",
        "summary": "Fallback heuristic result generated because OpenAI key was not provided.",
        "warnings": [
            "OpenAI API key not provided. Result generated using heuristic fallback.",
            "Review quantities and descriptions manually before using this output for budgeting.",
        ],
        "eap": [item.to_dict() for item in eap],
        "materials": [item.to_dict() for item in materials],
    }


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if not match:
        raise ValueError("The AI response did not contain JSON.")
    return json.loads(match.group(0))


def _call_openai(document_text: str, api_key: str, model: str) -> dict[str, Any]:
    client = OpenAI(api_key=api_key)
    prompt = f"""
You are helping engineers, architects and estimators.
Read the project text and return strict JSON only.

Return this shape:
{{
  "project_type": "string",
  "summary": "string",
  "warnings": ["string"],
  "eap": [
    {{
      "code": "string",
      "name": "string",
      "description": "string",
      "unit": "string",
      "quantity": "string",
      "confidence": 0.0,
      "children": []
    }}
  ],
  "materials": [
    {{
      "description": "string",
      "unit": "string",
      "quantity": "string",
      "source": "string",
      "confidence": 0.0,
      "category": "string"
    }}
  ]
}}

Rules:
- Do not add prices.
- Prefer real terms found in the project.
- If something is inferred, set low confidence and explain in warnings.
- Limit the response to practical items only.
- Keep the EAP hierarchical and concise.
- Produce at least one EAP branch and at least five materials when possible.

Project text:
{_clip(document_text)}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw_text = response.choices[0].message.content or "{}"
    return _parse_json_response(raw_text)


def _normalize_result(data: dict[str, Any], filename: str, pages, used_ai: bool) -> dict[str, Any]:
    eap = data.get("eap", [])
    materials = data.get("materials", [])
    warnings = data.get("warnings", [])

    def ensure_children(nodes):
        normalized = []
        for index, item in enumerate(nodes, start=1):
            children = ensure_children(item.get("children", []))
            normalized.append(
                {
                    "code": str(item.get("code") or index),
                    "name": str(item.get("name") or "Unnamed item"),
                    "description": str(item.get("description") or ""),
                    "unit": str(item.get("unit") or ""),
                    "quantity": str(item.get("quantity") or ""),
                    "confidence": float(item.get("confidence") or 0.0),
                    "children": children,
                }
            )
        return normalized

    def normalize_materials(items):
        normalized = []
        for item in items:
            normalized.append(
                {
                    "description": str(item.get("description") or ""),
                    "unit": str(item.get("unit") or ""),
                    "quantity": str(item.get("quantity") or ""),
                    "source": str(item.get("source") or ""),
                    "confidence": float(item.get("confidence") or 0.0),
                    "category": str(item.get("category") or ""),
                }
            )
        return normalized

    normalized_eap = ensure_children(eap)
    normalized_materials = normalize_materials(materials)

    if not normalized_eap:
        normalized_eap = [
            {
                "code": "1",
                "name": "Project analysis",
                "description": "Top level analysis generated automatically.",
                "unit": "",
                "quantity": "",
                "confidence": 0.5,
                "children": [],
            }
        ]

    if not normalized_materials:
        normalized_materials = [
            {
                "description": "Project review and structuring",
                "unit": "service",
                "quantity": "1",
                "source": "Derived from document analysis",
                "confidence": 0.4,
                "category": "Analysis",
            }
        ]

    return {
        "project_type": data.get("project_type", "Unknown"),
        "summary": data.get("summary", ""),
        "warnings": warnings,
        "eap": normalized_eap,
        "materials": normalized_materials,
        "metadata": {
            "filename": filename,
            "pages": len(pages),
            "text_char_count": sum(len(page.text) for page in pages),
            "used_ai": used_ai,
            "ocr_pages": sum(1 for page in pages if page.used_ocr),
        },
        "eap_count": _count_nodes(normalized_eap),
    }


def _count_nodes(items) -> int:
    total = 0
    for item in items:
        total += 1
        total += _count_nodes(item.get("children", []))
    return total


def process_pdf(file_bytes: bytes, filename: str, api_key: str | None, model: str) -> dict[str, Any]:
    pages = extract_pdf_pages(file_bytes)
    document_text = _compile_document_text(pages)

    if len(document_text.strip()) < 80:
        raise ValueError("The PDF did not contain enough readable text for analysis.")

    if api_key:
        try:
            data = _call_openai(document_text=document_text, api_key=api_key, model=model)
            return _normalize_result(data, filename=filename, pages=pages, used_ai=True)
        except Exception as exc:  # noqa: BLE001
            fallback = _heuristic_extract(document_text)
            fallback["warnings"].insert(0, f"OpenAI call failed, using fallback heuristic output: {exc}")
            return _normalize_result(fallback, filename=filename, pages=pages, used_ai=False)

    fallback = _heuristic_extract(document_text)
    return _normalize_result(fallback, filename=filename, pages=pages, used_ai=False)

