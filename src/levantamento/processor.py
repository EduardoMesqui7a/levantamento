from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from src.levantamento.pdf_tools import extract_pdf_pages


MAX_PAGES_FOR_VISION = 8
ENGINEER_SYSTEM_PROMPT = (
    "Você é um engenheiro estrutural sênior, com experiência em estruturas metálicas, "
    "leitura de pranchas técnicas, cortes, detalhes, hachuras, perfis, ligações, contraventamentos, "
    "chapas, parafusos, solda, pintura e planejamento de orçamento. "
    "Analise texto, desenho vetorial e imagens do PDF como um especialista humano faria."
)
VALIDATION_SYSTEM_PROMPT = (
    "Você é um auditor técnico de orçamento. Sua missão é revisar a saída de outro agente e "
    "remover itens que não sejam tecnicamente pertinentes. Mantenha o foco na disciplina correta."
)


def _clip(text: str, limit: int = 9000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[CONTEÚDO TRUNCADO]"


def _compile_document_text(pages) -> str:
    chunks = []
    for page in pages:
        header = (
            f"[PÁGINA {page.page_number} | OCR={page.used_ocr} | "
            f"VETORES={page.drawing_count} | IMAGENS={page.image_count}]"
        )
        chunks.append(
            f"{header}\n"
            f"Texto extraído:\n{page.text}\n"
            f"Resumo vetorial:\n{page.graphics_summary}"
        )
    return "\n\n".join(chunks)


def _build_multimodal_content(pages, include_images: bool = True) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Analise este PDF como um engenheiro estrutural sênior. "
                "Considere texto, linhas, hachuras, símbolos, perfis, cortes, detalhes e qualquer forma vetorial. "
                f"Considere até {MAX_PAGES_FOR_VISION} páginas na etapa visual."
            ),
        }
    ]

    for page in pages[:MAX_PAGES_FOR_VISION]:
        content.append(
            {
                "type": "text",
                "text": (
                    f"PÁGINA {page.page_number}\n"
                    f"Texto extraído:\n{_clip(page.text, 2500)}\n\n"
                    f"Resumo vetorial:\n{page.graphics_summary}"
                ),
            }
        )
        if include_images and page.image_data_uri:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": page.image_data_uri,
                        "detail": "high",
                    },
                }
            )

    return content


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if not match:
        raise ValueError("A resposta da IA não trouxe JSON válido.")
    return json.loads(match.group(0))


def _parse_model_json(response) -> dict[str, Any]:
    raw_text = response.choices[0].message.content or "{}"
    return _parse_json_response(raw_text)


def _profile_prompt() -> str:
    return f"""
Você é um engenheiro estrutural sênior analisando um projeto com texto, vetores e imagens.

Identifique com precisão a disciplina principal e o sistema estrutural do documento.
Se o conjunto de evidências apontar estrutura metálica, classifique explicitamente como estrutura metálica.
Não invente sistemas de concreto ou arquitetura sem evidência explícita.

Retorne SOMENTE JSON válido, em português, com esta estrutura:
{{
  "tipo_projeto": "string",
  "perfil_documento": {{
    "disciplina_principal": "string",
    "sistemas_identificados": ["string"],
    "evidencias_textuais": ["string"],
    "evidencias_visuais": ["string"],
    "itens_explicitos": ["string"],
    "itens_a_evitar": ["string"],
    "confianca": 0.0,
    "observacoes": "string"
  }}
}}

Regras:
- Seja conservador e técnico.
- Se houver qualquer indício visual forte de estrutura metálica, destaque isso.
- Considere linhas, hachuras, perfis, cortes, vistas e ligações como evidência.
- Responda somente com JSON.
""".strip()


def _extraction_prompt(profile: dict[str, Any]) -> str:
    return f"""
Você é um assistente especializado em orçamento de engenharia, arquitetura e levantamento quantitativo.

Use o perfil técnico abaixo como regra de contexto:
{json.dumps(profile, ensure_ascii=False, indent=2)}

Gere a EAP e a lista de materiais em português, com foco na disciplina principal identificada.
Se o perfil indicar estrutura metálica, priorize itens de estrutura metálica e exclua itens de concreto, alvenaria e arquitetura sem evidência explícita.

Retorne SOMENTE JSON válido com esta estrutura:
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
- Atue como engenheiro experiente, não como redator genérico.
- Estruture a EAP como uma árvore pronta para orçamento.
- Use numeração lógica na estrutura e organize por disciplinas e sistemas.
- Se o documento for de estrutura metálica, use categorias como perfis, chapas, ligações, parafusos, solda, pintura, montagem e inspeção quando fizer sentido.
- Mantenha o texto em português com acentuação correta.
- Não invente preços.
- Preencha preço unitário e total com 0.
- Quando um item for inferido, sinalize isso em observações e use menor confiança.
- Somente inclua materiais que sejam realmente materiais, componentes ou serviços técnicos pertinentes.
- Se o projeto estiver incompleto, ainda assim retorne uma estrutura útil.
- Crie ao menos 3 níveis de análise quando o conteúdo permitir.
""".strip()


def _validation_prompt(profile: dict[str, Any], parsed_payload: dict[str, Any]) -> str:
    return f"""
Você é uma etapa de validação de um agente de orçamento.

Revise o JSON abaixo e devolva uma versão final:
- mantenha apenas linhas realmente técnicas e pertinentes;
- remova observações genéricas, textos soltos e qualquer item que não seja material, componente, serviço técnico ou EAP;
- corrija acentuação e português;
- preserve o foco da disciplina principal;
- se o perfil indicar estrutura metálica, exclua itens de concreto/alvenaria/arquitetura que não tenham evidência explícita;
- mantenha preços zerados;
- responda somente com JSON válido e nada mais.

Perfil do documento:
{json.dumps(profile, ensure_ascii=False, indent=2)}

JSON atual:
{json.dumps(parsed_payload, ensure_ascii=False, indent=2)}
""".strip()


def _call_openai(api_key: str, model: str, pages) -> dict[str, Any]:
    client = OpenAI(api_key=api_key)

    profile_response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ENGINEER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_multimodal_content(pages, include_images=True)
                + [{"type": "text", "text": _profile_prompt()}],
            },
        ],
        temperature=0.2,
    )
    profile_data = _parse_model_json(profile_response)
    profile = profile_data.get("perfil_documento", {}) or {}

    extraction_response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ENGINEER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_multimodal_content(pages, include_images=True)
                + [{"type": "text", "text": _extraction_prompt(profile)}],
            },
        ],
        temperature=0.2,
    )
    extracted_data = _parse_model_json(extraction_response)

    validation_response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_multimodal_content(pages, include_images=False)
                + [{"type": "text", "text": _validation_prompt(profile, extracted_data)}],
            },
        ],
        temperature=0.1,
    )
    final_data = _parse_model_json(validation_response)
    if "perfil_documento" not in final_data:
        final_data["perfil_documento"] = profile
    return final_data


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
                "descricao": str(
                    item.get("descricao")
                    or item.get("description")
                    or item.get("name")
                    or "Item sem descrição"
                ),
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
    perfil_documento = data.get("perfil_documento", {}) or {}

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
        "perfil_documento": perfil_documento,
        "eap": eap,
        "materiais": materiais,
        "metadados": {
            "arquivo": filename,
            "paginas": len(pages),
            "caracteres_extraidos": sum(len(page.text) for page in pages),
            "uso_ia": used_ai,
            "paginas_ocr": sum(1 for page in pages if page.used_ocr),
            "paginas_vetoriais": sum(1 for page in pages if page.drawing_count > 0),
            "linhas_vetoriais": sum(page.line_count for page in pages),
            "retangulos_vetoriais": sum(page.rect_count for page in pages),
            "curvas_vetoriais": sum(page.curve_count for page in pages),
            "preenchimentos_vetoriais": sum(page.fill_count for page in pages),
            "imagens_embutidas": sum(page.image_count for page in pages),
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

    data = _call_openai(api_key=api_key, model=model, pages=pages)
    return _normalize_result(data, filename=filename, pages=pages, used_ai=True)
