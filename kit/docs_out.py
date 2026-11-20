"""문서 출력 부품 — 마크다운(AI 가 쓴 글) → HTML / Word(docx).

    from kit.docs_out import markdown_to_html, save_html, save_docx
    save_docx(md, "output/보고서.docx", title="주간 매출 보고")
    save_html(md, "output/보고서.html")       # 메일 본문·미리보기용
    fill_docx("양식.docx", {"거래처": "가산정밀"}, "output/확인서.docx")   # Word 양식의 {{거래처}} 채우기
"""
from __future__ import annotations

import re
from pathlib import Path

CSS = """
body{font-family:'맑은 고딕','Malgun Gothic',sans-serif;font-size:11pt;line-height:1.6;color:#222;max-width:900px;margin:24px auto;padding:0 16px}
h1{font-size:18pt;border-bottom:2px solid #1f4e79;padding-bottom:4px;color:#1f4e79}
h2{font-size:14pt;color:#1f4e79;margin-top:20px}h3{font-size:12pt}
table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #888;padding:4px 8px}
th{background:#dde7f3}code{background:#f3f3f3;padding:1px 4px}
"""


def markdown_to_html(md: str, title: str | None = None, for_hwp: bool = False) -> str:
    import markdown
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
    if for_hwp:  # 한글의 HTML 가져오기는 CSS 보다 속성을 잘 따름
        body = body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="4" width="100%">')
        body = body.replace("<th>", '<th bgcolor="#dde7f3">')
        body = body.replace("<img ", '<img width="520" ')  # 지정 안 하면 그림이 한 쪽을 다 차지
    head_title = f"<title>{title}</title>" if title else ""
    h1 = f"<h1>{title}</h1>" if title and not md.lstrip().startswith("# ") else ""
    return (f'<html><head><meta charset="utf-8">{head_title}<style>{CSS}</style></head>'
            f"<body>{h1}{body}</body></html>")


def save_html(md: str, path, title: str | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown_to_html(md, title), encoding="utf-8")
    return p


def _set_korean_font(run, name="맑은 고딕"):
    from docx.oxml.ns import qn
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)


def _add_inline(par, text: str):
    for i, chunk in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if chunk:
            r = par.add_run(chunk)
            r.bold = i % 2 == 1
            _set_korean_font(r)


def save_docx(md: str, path, title: str | None = None) -> Path:
    """간단 마크다운(#, -, 1., |표|, **굵게**) → docx."""
    import docx
    from docx.shared import Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.size = Pt(10.5)
    _set_korean_font_style(st)
    if title:
        h = d.add_heading(level=0)
        _add_inline(h, title)
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                t = d.add_table(rows=len(rows), cols=max(len(r) for r in rows))
                t.style = "Table Grid"
                for r, row in enumerate(rows):
                    for c, val in enumerate(row):
                        par = t.cell(r, c).paragraphs[0]
                        _add_inline(par, f"**{val}**" if r == 0 else val)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            _add_inline(d.add_heading(level=len(m.group(1))), m.group(2))
        elif re.match(r"^\s*[-*]\s+", line):
            _add_inline(d.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", line))
        elif re.match(r"^\s*\d+[.)]\s+", line):
            _add_inline(d.add_paragraph(style="List Number"), re.sub(r"^\s*\d+[.)]\s+", "", line))
        elif line.strip():
            _add_inline(d.add_paragraph(), line)
        i += 1
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(p))
    return p


def _set_korean_font_style(style, name="맑은 고딕"):
    from docx.oxml.ns import qn
    style.font.name = name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)


def fill_docx(template, values: dict, dst) -> Path:
    """Word 양식의 {{키}} 를 채웁니다 (본문·표·머리글·바닥글). 값을 안 준 자리표시는 빈칸.
    자리표시가 든 문단은 첫 글자 서식으로 통일됩니다 (문단 안에서 굵기가 섞여 있으면 풀림)."""
    import docx
    pat = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
    d = docx.Document(str(template))

    def fix(par):
        full = "".join(r.text for r in par.runs)
        if "{{" not in full or not par.runs:
            return
        par.runs[0].text = pat.sub(lambda m: str(values.get(m.group(1), "")), full)
        for r in par.runs[1:]:
            r.text = ""

    def walk(container):
        for par in container.paragraphs:
            fix(par)
        for t in container.tables:
            for row in t.rows:
                for c in row.cells:
                    walk(c)

    walk(d)
    for sec in d.sections:
        walk(sec.header)
        walk(sec.footer)
    p = Path(dst)
    p.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(p))
    return p
