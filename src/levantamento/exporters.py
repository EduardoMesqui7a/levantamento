import io
import json
from dataclasses import asdict, is_dataclass

import pandas as pd


def _flatten_eap(items, parent_path=None):
    parent_path = parent_path or []
    rows = []
    for item in items or []:
        path = parent_path + [item.get("name", "")]
        rows.append(
            {
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "unit": item.get("unit", ""),
                "quantity": item.get("quantity", ""),
                "confidence": item.get("confidence", 0.0),
                "path": " > ".join(filter(None, path)),
            }
        )
        rows.extend(_flatten_eap(item.get("children", []), path))
    return rows


def result_to_json(result) -> str:
    if is_dataclass(result):
        result = asdict(result)
    return json.dumps(result, ensure_ascii=False, indent=2)


class DataFrameExports:
    def __init__(self, result):
        self.result = result

    def to_excel_bytes(self) -> bytes:
        summary = pd.DataFrame(
            [
                {
                    "project_type": self.result.get("project_type", ""),
                    "document_name": self.result.get("metadata", {}).get("filename", ""),
                    "pages": self.result.get("metadata", {}).get("pages", 0),
                    "text_char_count": self.result.get("metadata", {}).get("text_char_count", 0),
                    "used_ai": self.result.get("metadata", {}).get("used_ai", False),
                }
            ]
        )
        eap_rows = pd.DataFrame(_flatten_eap(self.result.get("eap", [])))
        materials = pd.DataFrame(self.result.get("materials", []))
        warnings = pd.DataFrame({"warning": self.result.get("warnings", [])})

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            summary.to_excel(writer, index=False, sheet_name="Summary")
            eap_rows.to_excel(writer, index=False, sheet_name="EAP")
            materials.to_excel(writer, index=False, sheet_name="Materials")
            warnings.to_excel(writer, index=False, sheet_name="Warnings")
        return buffer.getvalue()


def dataframe_exports(result) -> DataFrameExports:
    return DataFrameExports(result)

