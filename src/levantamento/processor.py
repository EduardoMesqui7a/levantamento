from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from src.levantamento.models import EAPItem, MaterialItem
from src.levantamento.pdf_tools import extract_pdf_pages


def _clip(text: str, limit: int = 9000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[CONTEÚDO TRUNCADO]"


def _compile_document_text(pages) -> str:
    chunks = []
    for page in pages:
        header = f"[PÁGINA {page.page_number} | OCR={page.used_ocr}]"
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
        "forro",
        "laje",
        "impermeabilização",
    ]
    hits = [line for line in lines if any(keyword in line.lower() for keyword in keywords)]
    if not hits:
        hits = lines[:12]

    eap = [
        EAPItem(
            descricao="Levantamento preliminar e conferência geral do projeto",
            unidade="serviço",
            preco_unitario=0.0,
            preco_total=0.0,
            observacoes="Estrutura inicial gerada por heurística.",
            filhos=[
                EAPItem(
                    descricao="Leitura e interpretação do projeto",
                    unidade="serviço",
                    preco_unitario=0.0,
                    preco_total=0.0,
                ),
                EAPItem(
                    descricao="Estruturação da EAP por disciplinas",
                    unidade="serviço",
                    preco_unitario=0.0,
                    preco_total=0.0,
                ),
            ],
        ),
        EAPItem(
            descricao="Consolidação de materiais e componentes identificados",
            unidade="serviço",
            preco_unitario=0.0,
            preco_total=0.0,
            observacoes="Revisar manualmente antes de usar em orçamento.",
        ),
    ]

    materiais = []
    for idx, hit in enumerate(hits[:18], start=1):
        materiais.append(
            MaterialItem(
                descricao=hit[:140],
                unidade="un",
                quantidade="1",
                origem=f"Linha heurística {idx}",
                confianca=0.3,
                categoria="Heurística",
            )
        )

    return {
        "tipo_projeto": "Não identificado",
        "resumo": "Resultado gerado por heurística porque a IA não foi acionada.",
        "avisos": [
            "A chave da IA não foi encontrada. O sistema gerou uma estrutura inicial automática.",
            "Revise manualmente itens, unidades e quantidades antes de usar no orçamento.",
        ],
        "eap": [item.to_dict() for item in eap],
        "materiais": [item.to_dict() for item in materiais],
    }


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if not match:
        raise ValueError("A resposta da IA não trouxe JSON válido.")
    return json.loads(match.group(0))


def _call_openai(document_text: str, api_key: str, model: str) -> dict[str, Any]:
    client = OpenAI(api_key=api_key)
    prompt = f"""
Você é um assistente especializado em orçamentos de engenharia, arquitetura e levantamento quantitativo.

Leia o texto do projeto e retorne SOMENTE JSON válido, em português, com esta estrutura:
{{
  "tipo_projeto": "string",
  "resumo": "string",
  "avisos": ["string"],
  "eap": [
    {{
      "descricao": "string",
      "unidade": "string",
      "quantidade": "string",
      "preco_unitario": 0.0,
      "preco_total": 0.0,
      "observacoes": "string",
      "filhos": []
    }}
  ],
  "materiais": [
    {{
      "descricao": "string",
      "unidade": "string",
      "quantidade": "string",
      "origem": "string",
      "confianca": 0.0,
      "categoria": "string"
    }}
  ]
}}

Regras obrigatórias:
- Não invente preços.
- Preencha "preco_unitario" e "preco_total" com 0 quando não houver precificação.
- Estruture a EAP como uma árvore pronta para orçamento.
- Use numeração lógica na estrutura e organize por disciplinas e sistemas.
- Gere itens com cara de orçamento executivo, por exemplo: preliminares, estrutura, vedações, instalações, acabamentos, cobertura, esquadrias.
- Mantenha o texto em português com acentuação correta.
- Quando um item for inferido, indique isso em "observacoes" e use menor confiança.
- Prefira termos técnicos presentes no projeto.
- Se o projeto estiver incompleto, ainda assim retorne uma estrutura útil.
- Crie ao menos 3 níveis de análise quando o conteúdo permitir.

Texto do projeto:
{_clip(document_text)}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Responda somente com JSON válido em português."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw_text = response.choices[0].message.content or "{}"
    return _parse_json_response(raw_text)


def _normalize_materials(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for item in items:
        normalized.append(
            {
                "descricao": str(item.get("descricao") or item.get("description") or ""),
                "unidade": str(item.get("unidade") or item.get("unit") or ""),
                "quantidade": str(item.get("quantidade") or item.get("quantity") or ""),
                "origem": str(item.get("origem") or item.get("source") or ""),
                "confianca": float(item.get("confianca") or item.get("confidence") or 0.0),
                "categoria": str(item.get("categoria") or item.get("category") or ""),
            }
        )
    return normalized


def _normalize_eap_nodes(nodes: list[dict[str, Any]], parent_code: str = "") -> list[dict[str, Any]]:
    normalized = []
    for index, item in enumerate(nodes, start=1):
        code = f"{parent_code}.{index}" if parent_code else str(index)
        children_source = item.get("filhos") or item.get("children") or []
        children = _normalize_eap_nodes(children_source, code)
        normalized.append(
            {
                "item": code,
                "descricao": str(item.get("descricao") or item.get("description") or item.get("name") or "Item sem descrição"),
                "unidade": str(item.get("unidade") or item.get("unit") or ""),
                "quantidade": str(item.get("quantidade") or item.get("quantity") or ""),
                "preco_unitario": float(item.get("preco_unitario") or item.get("unit_price") or 0.0),
                "preco_total": float(item.get("preco_total") or item.get("total_price") or 0.0),
                "observacoes": str(item.get("observacoes") or item.get("description") or ""),
                "filhos": children,
            }
        )
    return normalized


def _count_nodes(items) -> int:
    total = 0
    for item in items:
        total += 1
        total += _count_nodes(item.get("filhos", []))
    return total


def _normalize_result(data: dict[str, Any], filename: str, pages, used_ai: bool) -> dict[str, Any]:
    eap = _normalize_eap_nodes(data.get("eap", []) or [])
    materiais = _normalize_materials(data.get("materiais", []) or data.get("materials", []) or [])
    avisos = list(data.get("avisos", []) or data.get("warnings", []) or [])

    if not eap:
        eap = [
            {
                "item": "1",
                "descricao": "Levantamento preliminar",
                "unidade": "serviço",
                "quantidade": "1",
                "preco_unitario": 0.0,
                "preco_total": 0.0,
                "observacoes": "Estrutura inicial gerada automaticamente.",
                "filhos": [
                    {
                        "item": "1.1",
                        "descricao": "Leitura e interpretação do projeto",
                        "unidade": "serviço",
                        "quantidade": "1",
                        "preco_unitario": 0.0,
                        "preco_total": 0.0,
                        "observacoes": "",
                        "filhos": [],
                    }
                ],
            }
        ]

    if not materiais:
        materiais = [
            {
                "descricao": "Levantamento técnico e estruturação da EAP",
                "unidade": "serviço",
                "quantidade": "1",
                "origem": "Análise do documento",
                "confianca": 0.4,
                "categoria": "Análise",
            }
        ]

    return {
        "tipo_projeto": data.get("tipo_projeto", "Não identificado"),
        "resumo": data.get("resumo", ""),
        "avisos": avisos,
        "eap": eap,
        "materiais": materiais,
        "metadados": {
            "arquivo": filename,
            "paginas": len(pages),
            "caracteres_extraidos": sum(len(page.text) for page in pages),
            "uso_ia": used_ai,
            "paginas_ocr": sum(1 for page in pages if page.used_ocr),
        },
        "total_itens_eap": _count_nodes(eap),
    }


def process_pdf(file_bytes: bytes, filename: str, api_key: str | None, model: str) -> dict[str, Any]:
    pages = extract_pdf_pages(file_bytes)
    document_text = _compile_document_text(pages)

    if len(document_text.strip()) < 80:
        raise ValueError("O PDF não possui texto legível suficiente para análise.")

    if api_key:
        try:
            data = _call_openai(document_text=document_text, api_key=api_key, model=model)
            return _normalize_result(data, filename=filename, pages=pages, used_ai=True)
        except Exception as exc:  # noqa: BLE001
            fallback = _heuristic_extract(document_text)
            fallback["avisos"].insert(0, f"Falha ao consultar a IA. Saída heurística usada: {exc}")
            return _normalize_result(fallback, filename=filename, pages=pages, used_ai=False)

    fallback = _heuristic_extract(document_text)
    return _normalize_result(fallback, filename=filename, pages=pages, used_ai=False)
