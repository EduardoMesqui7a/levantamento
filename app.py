import json
import os
from pathlib import Path

import streamlit as st

from src.levantamento.exporters import dataframe_exports, result_to_json
from src.levantamento.processor import process_pdf


APP_TITLE = "Project EAP Builder"
APP_SUBTITLE = "Upload a PDF and get an EAP plus a materials list."


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
    return (
        os.getenv("OPENAI_API_KEY")
        or _get_secret("OPENAI_API_KEY", "")
    )


def _render_tree(items, level: int = 0) -> None:
    for item in items:
        cols = st.columns([4, 1, 1, 1])
        indent = "    " * level
        cols[0].markdown(f"**{indent}{item.get('code', '')} {item.get('name', '')}**")
        cols[1].write(item.get("quantity", ""))
        cols[2].write(item.get("unit", ""))
        cols[3].write(f"{item.get('confidence', 0):.0%}")
        if item.get("description"):
            st.caption(item["description"])
        if item.get("children"):
            _render_tree(item["children"], level + 1)


def main() -> None:
    _load_env()
    st.set_page_config(page_title=APP_TITLE, page_icon=":page_facing_up:", layout="wide")

    st.title(APP_TITLE)
    st.write(APP_SUBTITLE)
    st.caption(
        "This MVP is designed for tests with PDF files first. If OpenAI credentials are not set, "
        "the app still produces a heuristic demo result so you can validate the flow."
    )

    with st.sidebar:
        st.header("Settings")
        st.text_input(
            "OpenAI model",
            value=os.getenv("OPENAI_MODEL", _get_secret("OPENAI_MODEL", "gpt-4o-mini")),
            key="openai_model",
        )
        api_key_loaded = bool(_get_api_key())
        if api_key_loaded:
            st.success("API key loaded automatically.")
        else:
            st.warning("No API key detected. Add one to .streamlit/secrets.toml or your environment.")
        st.caption("The key is never entered in the UI and is only read from secrets/environment.")

    uploaded = st.file_uploader("Upload project PDF", type=["pdf"])
    run = st.button("Process PDF", type="primary", disabled=uploaded is None)

    if "result" not in st.session_state:
        st.session_state.result = None
    if "raw_error" not in st.session_state:
        st.session_state.raw_error = None

    if run and uploaded is not None:
        with st.spinner("Processing file..."):
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
        st.info("Upload a PDF to start.")
        return

    summary = result.get("summary", "")
    warnings = result.get("warnings", [])
    meta = result.get("metadata", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pages", meta.get("pages", 0))
    c2.metric("Text chars", meta.get("text_char_count", 0))
    c3.metric("Materials", len(result.get("materials", [])))
    c4.metric("EAP nodes", result.get("eap_count", 0))

    if warnings:
        st.warning("\n".join(f"- {warning}" for warning in warnings))

    if summary:
        st.subheader("Project summary")
        st.write(summary)

    st.subheader("EAP tree")
    eap = result.get("eap", [])
    if eap:
        _render_tree(eap)
    else:
        st.info("No EAP items were generated.")

    st.subheader("Materials list")
    materials = result.get("materials", [])
    if materials:
        st.dataframe(materials, use_container_width=True, hide_index=True)
    else:
        st.info("No materials were generated.")

    st.subheader("Exports")
    json_payload = result_to_json(result)
    json_bytes = json_payload.encode("utf-8")
    st.download_button(
        "Download JSON",
        data=json_bytes,
        file_name="eap_materials.json",
        mime="application/json",
    )

    export_frames = dataframe_exports(result)
    excel_bytes = export_frames.to_excel_bytes()
    st.download_button(
        "Download Excel",
        data=excel_bytes,
        file_name="eap_materials.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with st.expander("Raw JSON"):
        st.code(json.dumps(result, ensure_ascii=False, indent=2), language="json")


if __name__ == "__main__":
    main()
