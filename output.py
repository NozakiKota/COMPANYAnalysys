"""
出力モジュール: 分析結果をExcel形式で保存する
NotebookLMフォルダ構造に相当するローカルディレクトリも作成する
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# 出力ルートディレクトリ
OUTPUT_ROOT = Path("output")

# カラーパレット
COLOR_HEADER = "1F4E79"      # 濃い青（ヘッダー）
COLOR_SUBHEADER = "2E75B6"   # 青（サブヘッダー）
COLOR_ROW_ODD = "DEEAF1"     # 薄い青（奇数行）
COLOR_ROW_EVEN = "FFFFFF"    # 白（偶数行）
COLOR_HIGH = "C6EFCE"        # 緑（高スコア）
COLOR_MID = "FFEB9C"         # 黄（中スコア）
COLOR_LOW = "FFC7CE"         # 赤（低スコア）
COLOR_PRIORITY = "FFD700"    # 金（最優先）


def _header_style(ws, cell_ref: str, value: str, bold: bool = True):
    cell = ws[cell_ref]
    cell.value = value
    cell.font = Font(bold=bold, color="FFFFFF", size=11)
    cell.fill = PatternFill("solid", fgColor=COLOR_HEADER)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = _thin_border()
    return cell


def _subheader_style(ws, cell_ref: str, value: str):
    cell = ws[cell_ref]
    cell.value = value
    cell.font = Font(bold=True, color="FFFFFF", size=10)
    cell.fill = PatternFill("solid", fgColor=COLOR_SUBHEADER)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = _thin_border()
    return cell


def _data_cell(ws, cell_ref: str, value: Any, row_idx: int = 0, wrap: bool = True):
    cell = ws[cell_ref]
    cell.value = value
    bg = COLOR_ROW_ODD if row_idx % 2 == 0 else COLOR_ROW_EVEN
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(vertical="top", wrap_text=wrap)
    cell.border = _thin_border()
    return cell


def _score_cell(ws, cell_ref: str, score: float, row_idx: int = 0):
    cell = ws[cell_ref]
    cell.value = score
    if score >= 4.0:
        fg = COLOR_HIGH
    elif score >= 2.5:
        fg = COLOR_MID
    else:
        fg = COLOR_LOW
    cell.fill = PatternFill("solid", fgColor=fg)
    cell.font = Font(bold=True)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = _thin_border()
    return cell


def _thin_border():
    side = Side(style="thin", color="BFBFBF")
    return Border(left=side, right=side, top=side, bottom=side)


def _set_col_width(ws, col: int, width: float):
    ws.column_dimensions[get_column_letter(col)].width = width


def create_company_folder(company_name: str) -> Path:
    """企業ごとのフォルダを作成（NotebookLMフォルダ相当）"""
    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in company_name)
    folder = OUTPUT_ROOT / safe_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_raw_ir_json(folder: Path, ir_data: dict[str, Any]) -> Path:
    """生のIRデータをJSONで保存"""
    path = folder / "ir_raw.json"
    path.write_text(json.dumps(ir_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_organized_json(folder: Path, organized: dict[str, Any]) -> Path:
    """整理済みデータをJSONで保存"""
    path = folder / "ir_organized.json"
    path.write_text(json.dumps(organized, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def create_ir_excel(
    company_name: str,
    organized: dict[str, Any],
    folder: Path,
) -> Path:
    """
    観点別IR情報一覧表 (Excel Sheet 1)
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "IR情報一覧"

    # タイトル
    ws.merge_cells("A1:F1")
    cell = ws["A1"]
    cell.value = f"【IR情報一覧】 {company_name}　　取得日: {datetime.now().strftime('%Y年%m月%d日')}"
    cell.font = Font(bold=True, size=14, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=COLOR_HEADER)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # ヘッダー行
    headers = ["No.", "分析観点", "要約", "具体的数値・事実", "出典・根拠", "年度"]
    for col, h in enumerate(headers, 1):
        _subheader_style(ws, f"{get_column_letter(col)}2", h)
    ws.row_dimensions[2].height = 20

    # 列幅
    widths = [5, 25, 45, 35, 30, 10]
    for col, w in enumerate(widths, 1):
        _set_col_width(ws, col, w)

    # データ行
    perspectives_data = organized.get("perspectives", {})
    for i, perspective in enumerate(perspectives_data.values(), 1):
        row = i + 2
        ws.row_dimensions[row].height = 60
        name = list(perspectives_data.keys())[i - 1]
        _data_cell(ws, f"A{row}", i, i)
        _data_cell(ws, f"B{row}", name, i)
        _data_cell(ws, f"C{row}", perspective.get("summary", ""), i)
        _data_cell(ws, f"D{row}", perspective.get("figures", perspective.get("details", "")), i)
        _data_cell(ws, f"E{row}", perspective.get("source", ""), i)
        _data_cell(ws, f"F{row}", perspective.get("year", ""), i)

    ws.freeze_panes = "A3"

    path = folder / f"{company_name}_IR分析.xlsx"
    wb.save(path)
    return path


def create_priority_excel(
    evaluation_result: dict[str, Any],
    all_organized: list[dict[str, Any]],
) -> Path:
    """
    全企業の優先順位評価表 (2シート構成)
    """
    OUTPUT_ROOT.mkdir(exist_ok=True)
    wb = openpyxl.Workbook()

    # ---- Sheet 1: 優先順位サマリー ----
    ws1 = wb.active
    ws1.title = "優先順位一覧"

    evaluations: list[dict] = evaluation_result.get("evaluations", [])
    evaluations.sort(key=lambda x: x.get("priority_rank", 99))

    # タイトル
    ws1.merge_cells("A1:J1")
    cell = ws1["A1"]
    cell.value = f"【顧客対応優先順位一覧】　作成日: {datetime.now().strftime('%Y年%m月%d日')}"
    cell.font = Font(bold=True, size=13, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=COLOR_HEADER)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 28

    from config import EVALUATION_CRITERIA
    criteria_names = [v["name"] for v in EVALUATION_CRITERIA.values()]
    headers = ["優先順位", "企業名", "総合スコア"] + criteria_names + ["推奨アクション", "主要商談機会"]
    for col, h in enumerate(headers, 1):
        _subheader_style(ws1, f"{get_column_letter(col)}2", h)
    ws1.row_dimensions[2].height = 25

    col_widths = [10, 25, 12] + [12] * len(criteria_names) + [30, 40]
    for col, w in enumerate(col_widths, 1):
        _set_col_width(ws1, col, w)

    for i, ev in enumerate(evaluations, 1):
        row = i + 2
        ws1.row_dimensions[row].height = 50
        rank = ev.get("priority_rank", i)

        # 1位は金色ハイライト
        rank_cell = ws1[f"A{row}"]
        rank_cell.value = f"第{rank}位"
        rank_cell.font = Font(bold=True, size=12, color="FFFFFF" if rank == 1 else "000000")
        rank_cell.fill = PatternFill("solid", fgColor=COLOR_PRIORITY if rank == 1 else (COLOR_ROW_ODD if i % 2 == 0 else COLOR_ROW_EVEN))
        rank_cell.alignment = Alignment(horizontal="center", vertical="center")
        rank_cell.border = _thin_border()

        _data_cell(ws1, f"B{row}", ev.get("company_name", ""), i)

        total = ev.get("weighted_total", 0)
        _score_cell(ws1, f"C{row}", round(total, 2), i)

        for j, key in enumerate(EVALUATION_CRITERIA.keys(), 4):
            score_data = ev.get("scores", {}).get(list(EVALUATION_CRITERIA.keys())[j - 4], {})
            score_val = score_data.get("score", 0) if isinstance(score_data, dict) else 0
            _score_cell(ws1, f"{get_column_letter(j)}{row}", score_val, i)

        col_action = 4 + len(EVALUATION_CRITERIA)
        _data_cell(ws1, f"{get_column_letter(col_action)}{row}", ev.get("recommended_action", ""), i)
        opportunities = ev.get("key_opportunities", [])
        _data_cell(ws1, f"{get_column_letter(col_action + 1)}{row}", "\n".join(f"・{o}" for o in opportunities), i)

    ws1.freeze_panes = "A3"

    # 全体所見
    last_row = len(evaluations) + 4
    ws1.merge_cells(f"A{last_row}:J{last_row + 3}")
    summary_cell = ws1[f"A{last_row}"]
    summary_cell.value = f"【全体所見】\n{evaluation_result.get('summary', '')}"
    summary_cell.font = Font(size=10)
    summary_cell.alignment = Alignment(vertical="top", wrap_text=True)
    summary_cell.fill = PatternFill("solid", fgColor="EBF3FA")
    summary_cell.border = _thin_border()
    ws1.row_dimensions[last_row].height = 80

    # ---- Sheet 2: スコア根拠詳細 ----
    ws2 = wb.create_sheet("評価根拠詳細")

    ws2.merge_cells("A1:E1")
    cell2 = ws2["A1"]
    cell2.value = "【評価根拠詳細】"
    cell2.font = Font(bold=True, size=13, color="FFFFFF")
    cell2.fill = PatternFill("solid", fgColor=COLOR_HEADER)
    cell2.alignment = Alignment(horizontal="center", vertical="center")
    ws2.row_dimensions[1].height = 28

    headers2 = ["企業名", "評価基準", "スコア", "根拠説明", "リスク"]
    for col, h in enumerate(headers2, 1):
        _subheader_style(ws2, f"{get_column_letter(col)}2", h)
    ws2.row_dimensions[2].height = 20

    for col, w in enumerate([20, 20, 10, 50, 35], 1):
        _set_col_width(ws2, col, w)

    row2 = 3
    for ev in evaluations:
        company = ev.get("company_name", "")
        scores = ev.get("scores", {})
        risks = ev.get("key_risks", [])
        risks_text = "\n".join(f"・{r}" for r in risks)

        for j, (key, crit) in enumerate(EVALUATION_CRITERIA.items()):
            ws2.row_dimensions[row2].height = 45
            score_data = scores.get(key, {})
            score_val = score_data.get("score", 0) if isinstance(score_data, dict) else 0
            rationale = score_data.get("rationale", "") if isinstance(score_data, dict) else ""

            _data_cell(ws2, f"A{row2}", company if j == 0 else "", row2)
            _data_cell(ws2, f"B{row2}", crit["name"], row2)
            _score_cell(ws2, f"C{row2}", score_val, row2)
            _data_cell(ws2, f"D{row2}", rationale, row2)
            _data_cell(ws2, f"E{row2}", risks_text if j == 0 else "", row2)
            row2 += 1

        # 企業間の区切り線
        for col in range(1, 6):
            cell_ref = f"{get_column_letter(col)}{row2 - 1}"
            ws2[cell_ref].border = Border(
                bottom=Side(style="medium", color="1F4E79"),
                left=Side(style="thin", color="BFBFBF"),
                right=Side(style="thin", color="BFBFBF"),
                top=Side(style="thin", color="BFBFBF"),
            )

    ws2.freeze_panes = "A3"

    path = OUTPUT_ROOT / f"顧客優先順位評価_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    wb.save(path)
    return path
