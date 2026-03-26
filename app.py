import json
import os
from pathlib import Path

import streamlit as st

from src.levantamento.exporters import dataframe_exports, result_to_json
from src.levantamento.processor import process_pdf


APP_TITLE = "EAP Orçamentária"
APP_SUBTITLE = "Envie um PDF de projeto e receba uma EAP pronta para orçamento, com lista de materiais."


def _load_env() -> None:
    env_file = Path(".env")
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        value = default
    return str(value or default)


def _get_api_key() -> str:
    return os.getenv("OPENAI_API_KEY") or _get_secret("OPENAI_API_KEY", "")


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(15, 118, 110, 0.10), transparent 32%),
                    linear-gradient(180deg, #F8FAFC 0%, #EEF2F7 100%);
                color: #0F172A;
            }
            .block-container {
                padding-top: 1.25rem;
                padding-bottom: 2.5rem;
                max-width: 1280px;
            }
            .hero {
                background: linear-gradient(135deg, #102A43 0%, #0F766E 55%, #134E4A 100%);
                color: white;
                border-radius: 28px;
                padding: 2rem 2rem 1.75rem 2rem;
                margin-bottom: 1.25rem;
                box-shadow: 0 18px 40px rgba(15, 23, 42, 0.16);
            }
            .hero h1 {
                margin: 0;
                font-size: 3rem;
                line-height: 1.05;
                letter-spacing: -0.03em;
            }
            .hero p {
                margin-top: 0.75rem;
                margin-bottom: 0;
                max-width: 860px;
                font-size: 1.02rem;
                color: rgba(255, 255, 255, 0.92);
            }
            .stMetric {
                background: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 18px;
                padding: 0.85rem 1rem;
            }
            div[data-testid="stFileUploaderDropzone"] {
                border-radius: 20px;
                border: 1px dashed rgba(15, 118, 110, 0.35);
                background: rgba(255, 255, 255, 0.85);
            }
            div[data-testid="stDataFrame"] {
                border-radius: 18px;
                overflow: hidden;
                border: 1px solid rgba(15, 23, 42, 0.08);
            }
            section[data-testid="stSidebar"] {
                background: linear-gradient(180deg, #F8FAFC 0%, #EEF2F7 100%);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_tree(items, level: int = 0) -> None:
    palette = ["#102A43", "#0F766E", "#0369A1", "#7C3AED"]
    for item in items:
        code = item.get("item", "")
        descricao = item.get("descricao", "")
        unidade = item.get("unidade", "")
        preco_unitario = item.get("preco_unitario", 0.0)
        preco_total = item.get("preco_total", 0.0)
        observacoes = item.get("observacoes", "")
        color = palette[min(level, len(palette) - 1)]
        st.markdown(
            f"""
            <div style="padding: 0.85rem 1rem; border-left: 5px solid {color}; margin: 0.35rem 0 0.65rem 0; background: rgba(255,255,255,0.82); border-radius: 14px;">
                <div style="display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap;">
                    <div>
                        <div style="font-weight:700; color:{color}; font-size:1rem;">{code} — {descricao}</div>
                        <div style="font-size:0.9rem; color:#475569; margin-top:0.25rem;">Unidade: {unidade or '—'} | Observações: {observacoes or '—'}</div>
                    </div>
                    <div style="text-align:right; min-width: 180px;">
                        <div style="font-size:0.86rem; color:#64748B;">Preço unitário</div>
                        <div style="font-weight:600; color:#0F172A;">R$ {preco_unitario:,.2f}</div>
                        <div style="font-size:0.86rem; color:#64748B; margin-top:0.35rem;">Preço total</div>
                        <div style="font-weight:600; color:#0F172A;">R$ {preco_total:,.2f}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if item.get("filhos"):
            _render_tree(item["filhos"], level + 1)


def _currency_formatter(value) -> str:
    try:
        return f"R$ {float(value):,.2f}"
    except Exception:  # noqa: BLE001
        return "R$ 0,00"


def main() -> None:
    _load_env()
    st.set_page_config(page_title=APP_TITLE, page_icon=":page_facing_up:", layout="wide")
    _inject_styles()

    st.markdown(
        f"""
        <div class="hero">
            <h1>{APP_TITLE}</h1>
            <p>{APP_SUBTITLE}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Configurações")
        st.text_input(
            "Modelo da IA",
            value=os.getenv("OPENAI_MODEL", _get_secret("OPENAI_MODEL", "gpt-4o-mini")),
            key="openai_model",
        )
        api_key_present = bool(_get_api_key())
        if api_key_present:
            st.success("Chave da IA carregada automaticamente.")
        else:
            st.warning("Nenhuma chave detectada. Adicione em `.streamlit/secrets.toml` ou nas variáveis do ambiente.")
        st.caption("A chave não é solicitada na interface. Ela é lida apenas de segredos ou do ambiente.")

    st.markdown("### Área de trabalho")
    uploaded = st.file_uploader("Enviar PDF do projeto", type=["pdf"])
    run = st.button("Gerar EAP e materiais", type="primary", disabled=uploaded is None or not api_key_present)

    if "result" not in st.session_state:
        st.session_state.result = None
    if "raw_error" not in st.session_state:
        st.session_state.raw_error = None

    if not api_key_present:
        st.error("A IA precisa estar configurada para gerar a EAP. Adicione a chave OpenAI nos segredos locais ou do Streamlit Cloud.")

    if run and uploaded is not None:
        with st.spinner("Analisando o projeto..."):
            try:
                st.session_state.result = process_pdf(
                    file_bytes=uploaded.getvalue(),
                    filename=uploaded.name,
                    api_key=_get_api_key() or None,
                    model=st.session_state.openai_model.strip() or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                )
                st.session_state.raw_error = None
            except Exception as exc:  # noqa: BLE001
                st.session_state.result = None
                st.session_state.raw_error = str(exc)

    if st.session_state.raw_error:
        st.error(st.session_state.raw_error)

    result = st.session_state.result
    if not result:
        st.info("Envie um PDF para começar.")
        return

    resumo = result.get("resumo", "")
    avisos = result.get("avisos", [])
    metadados = result.get("metadados", {})
    perfil = result.get("perfil_documento", {}) or {}
    auditoria = result.get("auditoria", {}) or {}

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Páginas", metadados.get("paginas", 0))
    c2.metric("Caracteres", metadados.get("caracteres_extraidos", 0))
    c3.metric("Materiais", len(result.get("materiais", [])))
    c4.metric("Itens da EAP", result.get("total_itens_eap", 0))

    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Páginas vetoriais", metadados.get("paginas_vetoriais", 0))
    v2.metric("Linhas", metadados.get("linhas_vetoriais", 0))
    v3.metric("Retângulos", metadados.get("retangulos_vetoriais", 0))
    v4.metric("Imagens", metadados.get("imagens_embutidas", 0))

    if perfil:
        disciplina = perfil.get("disciplina_principal", "Não identificada")
        confianca = float(perfil.get("confianca", 0.0) or 0.0)
        sistemas = perfil.get("sistemas_identificados", []) or []
        evidencias_textuais = perfil.get("evidencias_textuais", []) or []
        evidencias_visuais = perfil.get("evidencias_visuais", []) or []

        st.success(f"Classificação técnica: {disciplina} | Confiança: {confianca:.0%}")
        if sistemas:
            st.markdown("**Sistemas identificados**")
            st.write(", ".join(str(item) for item in sistemas))
        if evidencias_textuais or evidencias_visuais:
            with st.expander("Evidências usadas pela IA"):
                if evidencias_textuais:
                    st.markdown("**Textuais**")
                    st.write("\n".join(f"- {item}" for item in evidencias_textuais))
                if evidencias_visuais:
                    st.markdown("**Visuais**")
                    st.write("\n".join(f"- {item}" for item in evidencias_visuais))

    if auditoria:
        confianca_global = float(auditoria.get("confianca_global", 0.0) or 0.0)
        st.info(
            f"Auditoria técnica concluída | Confiança global da revisão: {confianca_global:.0%}"
        )
        with st.expander("Auditoria da IA"):
            sinais = auditoria.get("sinais_confirmados", []) or []
            criterios = auditoria.get("criterios_aceitacao", []) or []
            rejeitados = auditoria.get("itens_rejeitados", []) or []
            observacoes_finais = auditoria.get("observacoes_finais", "")

            if sinais:
                st.markdown("**Sinais confirmados**")
                st.write("\n".join(f"- {item}" for item in sinais))
            if criterios:
                st.markdown("**Critérios de aceitação**")
                st.write("\n".join(f"- {item}" for item in criterios))
            if rejeitados:
                st.markdown("**Itens rejeitados pela auditoria**")
                for item in rejeitados:
                    descricao = item.get("descricao", "")
                    motivo = item.get("motivo", "")
                    categoria = item.get("categoria", "")
                    st.write(f"- {descricao} | {categoria} | {motivo}")
            if observacoes_finais:
                st.markdown("**Observações finais**")
                st.write(observacoes_finais)

    if avisos:
        st.warning("\n".join(f"- {aviso}" for aviso in avisos))

    if resumo:
        st.markdown("### Resumo do projeto")
        st.write(resumo)

    st.markdown("### EAP estruturada")
    eap = result.get("eap", [])
    if eap:
        _render_tree(eap)
    else:
        st.info("Nenhum item de EAP foi gerado.")

    st.markdown("### Lista de materiais")
    materiais = dataframe_exports(result).materiais_dataframe()
    if not materiais.empty:
        materiais_visuais = materiais.copy()
        if "CONFIANÇA" in materiais_visuais.columns:
            materiais_visuais["CONFIANÇA"] = materiais_visuais["CONFIANÇA"].map(lambda v: f"{float(v) * 100:.0f}%")
        st.dataframe(
            materiais_visuais,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nenhum material foi gerado.")

    st.markdown("### Download")
    export_bundle = dataframe_exports(result)
    excel_bytes = export_bundle.to_excel_bytes()
    st.download_button(
        "Baixar planilha Excel",
        data=excel_bytes,
        file_name="EAP_Orcamentaria.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    json_payload = result_to_json(result)
    st.download_button(
        "Baixar JSON",
        data=json_payload.encode("utf-8"),
        file_name="EAP_Orcamentaria.json",
        mime="application/json",
    )

    with st.expander("JSON bruto"):
        st.code(json.dumps(result, ensure_ascii=False, indent=2), language="json")

    st.caption("A planilha Excel é gerada com cores, hierarquia e colunas prontas para orçamento.")


if __name__ == "__main__":
    main()
