from __future__ import annotations

import io
import json
from dataclasses import asdict, is_dataclass

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


PALETA = {
    "azul_escuro": "102A43",
    "verde": "0F766E",
    "verde_claro": "D1FAE5",
    "areia": "F8FAFC",
    "cinza": "E2E8F0",
    "texto": "0F172A",
    "branco": "FFFFFF",
    "amarelo": "FEF3C7",
}


def _flatten_eap(items, nivel: int = 0):
    rows = []
    for item in items or []:
        rows.append(
            {
                "item": item.get("item", ""),
                "descricao": item.get("descricao", ""),
                "unidade": item.get("unidade", ""),
                "preco_unitario": float(item.get("preco_unitario", 0.0) or 0.0),
                "preco_total": float(item.get("preco_total", 0.0) or 0.0),
                "nivel": nivel,
                "observacoes": item.get("observacoes", ""),
            }
        )
        rows.extend(_flatten_eap(item.get("filhos", []), nivel + 1))
    return rows


def _flatten_materiais(items):
    rows = []
    for item in items or []:
        rows.append(
            {
                "descricao": item.get("descricao", ""),
                "unidade": item.get("unidade", ""),
                "quantidade": item.get("quantidade", ""),
                "origem": item.get("origem", ""),
                "confianca": float(item.get("confianca", 0.0) or 0.0),
                "categoria": item.get("categoria", ""),
            }
        )
    return rows


def result_to_json(result) -> str:
    if is_dataclass(result):
        result = asdict(result)
    return json.dumps(result, ensure_ascii=False, indent=2)


class DataFrameExports:
    def __init__(self, result):
        self.result = result

    def eap_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(_flatten_eap(self.result.get("eap", [])))
        if df.empty:
            return pd.DataFrame(columns=["ITEM", "DESCRIÇÃO", "UNIDADE", "PREÇO UNITÁRIO", "PREÇO TOTAL", "NÍVEL", "OBSERVAÇÕES"])
        return df.rename(
            columns={
                "item": "ITEM",
                "descricao": "DESCRIÇÃO",
                "unidade": "UNIDADE",
                "preco_unitario": "PREÇO UNITÁRIO",
                "preco_total": "PREÇO TOTAL",
                "nivel": "NÍVEL",
                "observacoes": "OBSERVAÇÕES",
            }
        )

    def materiais_dataframe(self) -> pd.DataFrame:
        df = pd.DataFrame(_flatten_materiais(self.result.get("materiais", [])))
        if df.empty:
            return pd.DataFrame(columns=["DESCRIÇÃO", "UNIDADE", "QUANTIDADE", "ORIGEM", "CONFIANÇA", "CATEGORIA"])
        return df.rename(
            columns={
                "descricao": "DESCRIÇÃO",
                "unidade": "UNIDADE",
                "quantidade": "QUANTIDADE",
                "origem": "ORIGEM",
                "confianca": "CONFIANÇA",
                "categoria": "CATEGORIA",
            }
        )

    def _write_title_block(self, ws) -> None:
        ws["A1"] = "EAP ORÇAMENTÁRIA"
        ws["A1"].font = Font(size=18, bold=True, color=PALETA["verde"])
        ws["A2"] = f"Projeto: {self.result.get('tipo_projeto', 'Não identificado')}"
        ws["A2"].font = Font(size=11, color=PALETA["texto"])
        ws["A3"] = f"Resumo: {self.result.get('resumo', '')}"
        ws["A3"].font = Font(size=10, color=PALETA["texto"])
        ws["A4"] = f"Total de itens da EAP: {self.result.get('total_itens_eap', 0)}"
        ws["A4"].font = Font(size=10, color=PALETA["texto"])

    def _style_sheet(self, ws, header_row: int, freeze_cell: str) -> None:
        thin = Side(style="thin", color=PALETA["cinza"])
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        header_fill = PatternFill("solid", fgColor=PALETA["verde"])
        title_fill = PatternFill("solid", fgColor=PALETA["verde_claro"])

        for row in ws.iter_rows():
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        for cell in ws[header_row]:
            cell.fill = header_fill
            cell.font = Font(color=PALETA["branco"], bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.freeze_panes = freeze_cell
        ws.sheet_view.showGridLines = False

        for row in range(1, 5):
            for col in range(1, ws.max_column + 1):
                ws.cell(row=row, column=col).fill = title_fill

    def _set_widths(self, ws, widths: dict[str, float]) -> None:
        for col, width in widths.items():
            ws.column_dimensions[col].width = width

    def _style_budget_rows(self, ws, start_row: int, max_row: int) -> None:
        fills = {
            0: PatternFill("solid", fgColor="EFF6FF"),
            1: PatternFill("solid", fgColor="F0FDFA"),
            2: PatternFill("solid", fgColor="FFFBEB"),
            3: PatternFill("solid", fgColor="F8FAFC"),
        }
        currency = '"R$" #,##0.00'
        thin = Side(style="thin", color=PALETA["cinza"])
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for row in range(start_row, max_row + 1):
            nivel = int(ws.cell(row=row, column=6).value or 0)
            fill = fills.get(min(nivel, 3), fills[3])
            for col in range(1, 6):
                cell = ws.cell(row=row, column=col)
                cell.fill = fill
                cell.border = border
                if col == 2:
                    indent = max(nivel, 0) * 2
                    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True, indent=indent)
                elif col in (1, 3):
                    cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
                else:
                    cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)

            ws.cell(row=row, column=4).number_format = currency
            ws.cell(row=row, column=5).number_format = currency

    def to_excel_bytes(self) -> bytes:
        wb = Workbook()
        ws_orc = wb.active
        ws_orc.title = "Orçamento"

        self._write_title_block(ws_orc)

        headers = ["ITEM", "DESCRIÇÃO", "UNIDADE", "PREÇO UNITÁRIO", "PREÇO TOTAL", "NÍVEL", "OBSERVAÇÕES"]
        header_row = 6
        for col, header in enumerate(headers, start=1):
            cell = ws_orc.cell(row=header_row, column=col, value=header)
            cell.font = Font(bold=True, color=PALETA["branco"])
            cell.fill = PatternFill("solid", fgColor=PALETA["azul_escuro"])
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for row_idx, row in enumerate(_flatten_eap(self.result.get("eap", [])), start=header_row + 1):
            ws_orc.cell(row=row_idx, column=1, value=row["item"])
            ws_orc.cell(row=row_idx, column=2, value=row["descricao"])
            ws_orc.cell(row=row_idx, column=3, value=row["unidade"])
            ws_orc.cell(row=row_idx, column=4, value=row["preco_unitario"])
            ws_orc.cell(row=row_idx, column=5, value=row["preco_total"])
            ws_orc.cell(row=row_idx, column=6, value=row["nivel"])
            ws_orc.cell(row=row_idx, column=7, value=row["observacoes"])

        self._style_budget_rows(ws_orc, start_row=header_row + 1, max_row=ws_orc.max_row)
        self._style_sheet(ws_orc, header_row=header_row, freeze_cell="A7")
        self._set_widths(
            ws_orc,
            {
                "A": 12,
                "B": 58,
                "C": 14,
                "D": 18,
                "E": 18,
                "F": 10,
                "G": 42,
            },
        )

        ws_materiais = wb.create_sheet("Materiais")
        ws_materiais["A1"] = "LISTA DE MATERIAIS"
        ws_materiais["A1"].font = Font(size=18, bold=True, color=PALETA["verde"])
        ws_materiais["A2"] = f"Projeto: {self.result.get('tipo_projeto', 'Não identificado')}"
        ws_materiais["A2"].font = Font(size=11, color=PALETA["texto"])

        material_headers = ["DESCRIÇÃO", "UNIDADE", "QUANTIDADE", "ORIGEM", "CONFIANÇA", "CATEGORIA"]
        for col, header in enumerate(material_headers, start=1):
            cell = ws_materiais.cell(row=4, column=col, value=header)
            cell.font = Font(bold=True, color=PALETA["branco"])
            cell.fill = PatternFill("solid", fgColor=PALETA["azul_escuro"])
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for row_idx, row in enumerate(_flatten_materiais(self.result.get("materiais", [])), start=5):
            ws_materiais.cell(row=row_idx, column=1, value=row["descricao"])
            ws_materiais.cell(row=row_idx, column=2, value=row["unidade"])
            ws_materiais.cell(row=row_idx, column=3, value=row["quantidade"])
            ws_materiais.cell(row=row_idx, column=4, value=row["origem"])
            ws_materiais.cell(row=row_idx, column=5, value=row["confianca"])
            ws_materiais.cell(row=row_idx, column=6, value=row["categoria"])

        self._style_sheet(ws_materiais, header_row=4, freeze_cell="A5")
        for cell in ws_materiais[4]:
            cell.fill = PatternFill("solid", fgColor=PALETA["verde"])
        for row in range(5, ws_materiais.max_row + 1):
            ws_materiais.cell(row=row, column=5).number_format = '0.0%'
        self._set_widths(
            ws_materiais,
            {
                "A": 56,
                "B": 12,
                "C": 12,
                "D": 34,
                "E": 12,
                "F": 18,
            },
        )

        ws_resumo = wb.create_sheet("Resumo")
        ws_resumo["A1"] = "RESUMO DO LEVANTAMENTO"
        ws_resumo["A1"].font = Font(size=18, bold=True, color=PALETA["verde"])
        resumo_linhas = [
            ("Tipo de projeto", self.result.get("tipo_projeto", "Não identificado")),
            ("Resumo", self.result.get("resumo", "")),
            ("Avisos", " | ".join(self.result.get("avisos", [])) or "Nenhum"),
            ("Arquivo de origem", self.result.get("metadados", {}).get("arquivo", "")),
            ("Páginas processadas", self.result.get("metadados", {}).get("paginas", 0)),
            ("Páginas com OCR", self.result.get("metadados", {}).get("paginas_ocr", 0)),
            ("Total de itens da EAP", self.result.get("total_itens_eap", 0)),
        ]
        for row_idx, (label, value) in enumerate(resumo_linhas, start=3):
            ws_resumo.cell(row=row_idx, column=1, value=label)
            ws_resumo.cell(row=row_idx, column=2, value=value)
            ws_resumo.cell(row=row_idx, column=1).font = Font(bold=True, color=PALETA["texto"])
            ws_resumo.cell(row=row_idx, column=2).alignment = Alignment(wrap_text=True)
        self._set_widths(ws_resumo, {"A": 22, "B": 84})

        buffer = io.BytesIO()
        wb.save(buffer)
        return buffer.getvalue()


def dataframe_exports(result) -> DataFrameExports:
    return DataFrameExports(result)
