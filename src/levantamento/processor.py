from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

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
    prompt_analise = f"""
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
            {"role": "user", "content": prompt_analise},
        ],
        temperature=0.2,
    )
    raw_text = response.choices[0].message.content or "{}"
    parsed = _parse_json_response(raw_text)
    return _review_and_refine_with_ai(client=client, model=model, document_text=document_text, parsed_payload=parsed)


def _review_and_refine_with_ai(client: OpenAI, model: str, document_text: str, parsed_payload: dict[str, Any]) -> dict[str, Any]:
    prompt_revisao = f"""
Você é uma etapa de validação de um agente de IA de orçamento.

Sua tarefa é revisar o JSON abaixo e devolver uma versão final:
- mantenha apenas linhas que sejam realmente materiais, componentes, serviços técnicos de orçamento ou itens da EAP;
- remova texto de observação, conclusão, recomendação geral, títulos soltos e frases que não representem material;
- corrija acentuação e português;
- mantenha a estrutura em português;
- garanta que a EAP tenha numeração lógica;
- garanta que os materiais sejam objetivos e pertinentes;
- se um item for dúvida, reduza a confiança ou exclua;
- se faltar informação, ajuste para um resultado mais conservador;
- não adicione preços reais, apenas zero nas colunas de preço;
- responda somente com JSON válido e nada mais.

Texto do projeto:
{_clip(document_text)}

JSON atual:
{json.dumps(parsed_payload, ensure_ascii=False, indent=2)}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Você revisa e corrige saídas de um agente de orçamento. Responda somente com JSON."},
            {"role": "user", "content": prompt_revisao},
        ],
        temperature=0.1,
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
                "preco_unitario": 0.0,
                "preco_total": 0.0,
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

    if not api_key:
        raise RuntimeError("A IA não pode ser acionada sem OPENAI_API_KEY configurada.")

    data = _call_openai(document_text=document_text, api_key=api_key, model=model)
    return _normalize_result(data, filename=filename, pages=pages, used_ai=True)
