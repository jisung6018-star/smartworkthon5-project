"""엑셀 보고서 부품 — 현업이 바로 쓰는 '예쁜' 엑셀.

    from kit.excel_out import save_excel, add_chart, records_to_tables
    save_excel({"주문목록": df1, "품목별합계": df2}, "output/주문정리.xlsx",
               title="11월 발주 정리", totals=True,
               highlight={"긴급도": {"높음": "FFC7CE", "보통": "FFEB9C"}})
    add_chart("output/주문정리.xlsx", "품목별합계", category="품명", values=["수량"], title="품목별 주문량")

    main, details = records_to_tables(ai_results)   # ask_json 결과(중첩 목록 포함) → 표 여러 개
    fill_template("양식.xlsx", {"거래처": "가산정밀"}, "output/견적서.xlsx",
                  rows={"품목": [{"품명": "볼트", "수량": 100, "단가": 120, "금액": 12000}]})
        # 회사 엑셀 양식의 {{거래처}} 와 {{품목.품명}} 행을 채움 (서식·수식 유지)
"""
from __future__ import annotations

import re
from copy import copy
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
TOTAL_FILL = PatternFill("solid", fgColor="DDE7F3")
THIN = Side(style="thin", color="A6A6A6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _width(v) -> int:
    s = "" if v is None else str(v)
    return sum(2 if ord(ch) > 127 else 1 for ch in s.split("\n")[0])


def save_excel(data, path, title: str | None = None, totals: bool = False,
               money_cols: tuple | list = (), pct_cols: tuple | list = (),
               highlight: dict | None = None, index: bool = False) -> Path:
    """DataFrame 또는 {시트명: DataFrame} → 서식 입힌 xlsx.
    totals=True 면 숫자 열에 SUM 수식 합계 행 추가 (엑셀에서 값 고치면 합계도 바뀜).
    highlight={"열이름": {"값": "색(hex)"}} 이면 해당 행 색칠."""
    sheets = data if isinstance(data, dict) else {"Sheet1": data}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    start = 2 if title else 0
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=str(name)[:31], index=index, startrow=start)
    wb = load_workbook(p)
    for name, df in sheets.items():
        ws = wb[str(name)[:31]]
        d = df.reset_index() if index else df
        hdr = start + 1
        ncol, nrow = len(d.columns), len(d)
        if title:
            ws.cell(1, 1, title).font = Font(size=14, bold=True, color="1F4E79")
            if ncol > 1:
                ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
        for c in range(1, ncol + 1):
            cell = ws.cell(hdr, c)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = BORDER
        numeric = {c for c in d.columns if pd.api.types.is_numeric_dtype(d[c]) and not pd.api.types.is_bool_dtype(d[c])}
        for ci, col in enumerate(d.columns, 1):
            fmt = None
            if col in pct_cols:
                fmt = "0.0%"
            elif col in money_cols or col in numeric:
                fmt = "#,##0" if col in money_cols or pd.api.types.is_integer_dtype(d[col]) else "#,##0.##"
            for r in range(hdr + 1, hdr + nrow + 1):
                cell = ws.cell(r, ci)
                cell.border = BORDER
                cell.alignment = Alignment(vertical="top", wrap_text=isinstance(cell.value, str) and len(cell.value) > 40)
                if fmt:
                    cell.number_format = fmt
        if highlight:
            for col, colors in highlight.items():
                if col not in d.columns:
                    continue
                ci = list(d.columns).index(col) + 1
                for r in range(hdr + 1, hdr + nrow + 1):
                    color = colors.get(str(ws.cell(r, ci).value))
                    if color:
                        for c in range(1, ncol + 1):
                            ws.cell(r, c).fill = PatternFill("solid", fgColor=color)
        if totals and nrow:
            tr = hdr + nrow + 1
            ws.cell(tr, 1, "합계").font = Font(bold=True)
            for ci, col in enumerate(d.columns, 1):
                cell = ws.cell(tr, ci)
                if col in numeric and ci > 1:
                    L = get_column_letter(ci)
                    cell.value = f"=SUM({L}{hdr + 1}:{L}{hdr + nrow})"
                    cell.number_format = "#,##0"
                    cell.font = Font(bold=True)
                cell.fill, cell.border = TOTAL_FILL, BORDER
        for ci, col in enumerate(d.columns, 1):
            vals = [col] + d[col].head(200).tolist()
            ws.column_dimensions[get_column_letter(ci)].width = min(60, max(8, max(_width(v) for v in vals) + 2))
        ws.freeze_panes = ws.cell(hdr + 1, 1)
        if nrow:
            ws.auto_filter.ref = f"A{hdr}:{get_column_letter(ncol)}{hdr + nrow}"
    wb.save(p)
    return p


def add_chart(path, sheet: str, category: str, values: list[str], title: str | None = None,
              kind: str = "bar", anchor: str | None = None) -> Path:
    """엑셀 안에 진짜 엑셀 차트 추가 (save_excel 로 만든 시트 기준). kind: bar(세로)|barh(가로)|line|pie"""
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    wb = load_workbook(path)
    ws = wb[sheet]
    hdr = next(r for r in range(1, 6) if any(ws.cell(r, c).value == category for c in range(1, ws.max_column + 1)))
    cols = {ws.cell(hdr, c).value: c for c in range(1, ws.max_column + 1)}
    last = hdr
    while ws.cell(last + 1, cols[category]).value not in (None, "합계"):
        last += 1
    chart = {"bar": BarChart, "barh": BarChart, "line": LineChart, "pie": PieChart}[kind]()
    if kind in ("bar", "barh"):
        chart.type = "col" if kind == "bar" else "bar"  # openpyxl: col=세로, bar=가로
    for v in values:
        chart.add_data(Reference(ws, min_col=cols[v], min_row=hdr, max_row=last), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=cols[category], min_row=hdr + 1, max_row=last))
    chart.title = title
    chart.height, chart.width = 8, 16
    ws.add_chart(chart, anchor or f"{get_column_letter(ws.max_column + 2)}{hdr}")
    wb.save(path)
    return Path(path)


def records_to_tables(records: list[dict], id_col: str = "번호") -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """AI 추출 결과 목록 → (요약표, {목록필드명: 상세표}). 상세표에는 id_col 로 요약표와 연결."""
    main_rows, details = [], {}
    for i, rec in enumerate(records, 1):
        row = {id_col: i}
        for k, v in (rec or {}).items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                details.setdefault(k, []).extend({id_col: i, **item} for item in v)
                row[f"{k}_건수"] = len(v)
            elif isinstance(v, list):
                row[k] = ", ".join(map(str, v))
            elif isinstance(v, dict):
                row.update({f"{k}_{kk}": vv for kk, vv in v.items()})
            else:
                row[k] = v
        main_rows.append(row)
    return pd.DataFrame(main_rows), {k: pd.DataFrame(v) for k, v in details.items()}


def to_bytes(data, **kw) -> bytes:
    """Streamlit 다운로드 버튼용."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = save_excel(data, Path(d) / "out.xlsx", **kw)
        return p.read_bytes()


_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def fill_template(template, values: dict, dst, rows: dict | None = None) -> Path:
    """엑셀 양식의 {{키}} 를 채웁니다 (서식·수식·병합 유지). 값을 안 준 자리표시는 빈칸.
    rows={"품목": [{...}, ...]} 를 주면 {{품목.품명}} 이 적힌 칸부터 아래로 한 줄씩 채웁니다
    (양식에 빈 줄이 충분히 있어야 함 — 행을 새로 끼워 넣지는 않습니다)."""
    wb = load_workbook(template)
    rows = rows or {}
    for ws in wb.worksheets:
        lists = []
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not isinstance(v, str) or "{{" not in v:
                    continue
                whole = _PLACEHOLDER.fullmatch(v.strip())
                if whole and "." in whole.group(1) and whole.group(1).split(".", 1)[0] in rows:
                    lists.append((cell, *whole.group(1).split(".", 1)))
                elif whole:          # 칸 전체가 자리표시 → 숫자는 숫자 그대로 (합계 수식이 동작)
                    cell.value = values.get(whole.group(1), "")
                else:
                    cell.value = _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), v)
        for cell, name, field in lists:
            recs = rows[name]
            if not recs:
                cell.value = ""
            for k, rec in enumerate(recs):
                tgt = ws.cell(cell.row + k, cell.column)
                try:
                    tgt.value = rec.get(field, "")
                    if k:
                        tgt._style = copy(cell._style)
                except AttributeError:   # 병합된 칸의 일부는 쓸 수 없음
                    pass
    p = Path(dst)
    p.parent.mkdir(parents=True, exist_ok=True)
    wb.save(p)
    return p
